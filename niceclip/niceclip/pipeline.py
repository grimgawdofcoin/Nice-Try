"""The end-to-end job: probe → audio proxy → detect dead air → transcribe
(active regions only) → (scenes) → score → (Claude re-rank) → render clips
→ (optional dead-air-free full export).

Progress budget (of 100): probe 2, audio+dead-air-detect 11, transcribe 42,
scenes 6, scoring 3, dead-air export 8 (only if requested), rendering the
rest.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import analyzer, editor, ffmpeg_utils as ff, llm
from .analyzer import Analysis
from .jobs import Job

DEFAULT_SETTINGS = {
    "clip_count": 5,
    "min_len": 15,
    "max_len": 60,
    "aspect": "vertical",          # vertical | square | original
    "vertical_mode": "fit",        # fit | crop
    "captions": True,
    "transcribe": True,
    "whisper_model": "small",      # tiny | base | small | medium
    "scene_detection": False,
    "ai_ranking": True,
    "ai_model": llm.DEFAULT_MODEL,
    "cut_dead_air": False,         # export a full copy with silence removed
}


def _fmt_duration(seconds: float) -> str:
    """Human-scale duration for warning messages — hours for long tape,
    minutes for anything under an hour, so a 20-minute clip with 2 minutes
    of talk doesn't get rounded down to '0.0h'."""
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.0f}s"


def merge_settings(settings: dict | None) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    for k, v in (settings or {}).items():
        if k in merged and v is not None:
            merged[k] = v
    merged["clip_count"] = max(1, min(20, int(merged["clip_count"])))
    merged["min_len"] = max(5, min(120, float(merged["min_len"])))
    merged["max_len"] = max(merged["min_len"] + 5, min(180, float(merged["max_len"])))
    return merged


class PipelineRunner:
    def __init__(self, output_root: Path, work_root: Path):
        self.output_root = output_root
        self.work_root = work_root

    def __call__(self, job: Job) -> None:
        s = merge_settings(job.settings)
        job.settings = s
        src = Path(job.source)
        if not src.is_file():
            raise FileNotFoundError(f"Source video not found: {src}")

        workdir = self.work_root / job.id
        workdir.mkdir(parents=True, exist_ok=True)
        outdir = self.output_root / job.id
        outdir.mkdir(parents=True, exist_ok=True)

        try:
            job.set_stage("Probing video", 1)
            info = ff.probe(src)
            if not info.has_video or info.duration <= 0:
                raise RuntimeError(
                    "Could not read this file as a video (no video stream or "
                    "unknown duration)."
                )
            if info.duration < s["min_len"]:
                raise RuntimeError(
                    f"Video is shorter ({info.duration:.0f}s) than the minimum "
                    f"clip length ({s['min_len']:.0f}s)."
                )
            analysis = Analysis(duration=info.duration)

            job.set_stage("Extracting audio", 2)
            wav = workdir / "audio.wav"
            active_regions: list[tuple[float, float]] = []
            trimmed_for_transcription = False
            if info.has_audio:
                analyzer.extract_audio(
                    src, wav, info.duration,
                    on_progress=job.stage_progress(2, 9),
                    cancel_event=job.cancel_event,
                )
                job.set_stage("Detecting dead air", 11)
                raw_rms = analyzer.compute_energy(wav)
                analysis.energy = analyzer.normalize_energy(raw_rms)
                active_regions = analyzer.detect_active_regions(raw_rms, info.duration)
                if not active_regions:
                    job.warnings.append(
                        "Couldn't detect distinct speech/activity in the "
                        "audio — treating the whole recording as active."
                    )
                    active_regions = [(0.0, info.duration)]
                analysis.active_regions = active_regions
                active_dur = analyzer.regions_duration(active_regions)
                trimmed_for_transcription = 0 < active_dur < info.duration * 0.95
                if trimmed_for_transcription:
                    saved = info.duration - active_dur
                    job.warnings.append(
                        f"Detected {_fmt_duration(active_dur)} of activity out "
                        f"of {_fmt_duration(info.duration)} — skipped "
                        f"~{_fmt_duration(saved)} of dead air for "
                        "transcription and clip selection."
                    )
            else:
                job.warnings.append("Video has no audio track — using visual/"
                                    "spacing heuristics only.")
                if s["cut_dead_air"]:
                    job.warnings.append(
                        "Cut dead air skipped: no audio track to detect "
                        "activity from."
                    )

            self._check_cancel(job)
            if s["transcribe"] and info.has_audio:
                transcribe_target, transcribe_duration = wav, info.duration
                if trimmed_for_transcription:
                    job.set_stage("Trimming dead air before transcription", 12)
                    trimmed_wav = workdir / "audio_active.wav"
                    analyzer.build_trimmed_wav(wav, active_regions, trimmed_wav)
                    transcribe_target = trimmed_wav
                    transcribe_duration = analyzer.regions_duration(active_regions)
                job.set_stage(
                    f"Transcribing speech (Whisper {s['whisper_model']}) — "
                    "this is the slow part", 13)
                segments = analyzer.transcribe(
                    transcribe_target, transcribe_duration, s["whisper_model"],
                    on_progress=job.stage_progress(13, 42),
                    cancel_event=job.cancel_event,
                )
                if segments is None:
                    job.warnings.append(
                        "faster-whisper is not installed — clips were chosen "
                        "by audio energy alone, and captions are unavailable."
                    )
                else:
                    if trimmed_for_transcription:
                        segments = analyzer.remap_segments(segments, active_regions)
                    analysis.segments = segments
                    analysis.transcript_available = True
            job.set_stage("Transcription done", 55)

            self._check_cancel(job)
            if s["scene_detection"]:
                job.set_stage("Detecting scene changes", 56)
                try:
                    analysis.scene_times = analyzer.detect_scenes(
                        src, cancel_event=job.cancel_event)
                except ff.Cancelled:
                    raise
                except Exception:
                    job.warnings.append("Scene detection failed; continuing "
                                        "without it.")

            job.set_stage("Scoring highlight candidates", 61)
            candidates = analyzer.build_candidates(
                analysis, min_len=s["min_len"], max_len=s["max_len"])
            if not candidates:
                raise RuntimeError("No usable clip candidates were found.")

            picked = None
            if s["ai_ranking"] and analysis.transcript_available:
                if llm.claude_available():
                    job.set_stage("AI ranking (Claude)", 62)
                    picked = llm.rank_with_claude(
                        candidates, s["clip_count"], model=s["ai_model"])
                    if picked is None:
                        job.warnings.append(
                            "AI ranking unavailable or failed — used built-in "
                            "heuristic ranking instead."
                        )
                else:
                    job.warnings.append(
                        "AI ranking skipped: set ANTHROPIC_API_KEY to enable "
                        "Claude-powered clip selection."
                    )
            chosen = (picked or candidates)[: s["clip_count"]]

            self._check_cancel(job)

            do_export = bool(s["cut_dead_air"]) and trimmed_for_transcription
            if s["cut_dead_air"] and info.has_audio and not trimmed_for_transcription:
                job.warnings.append(
                    "No significant dead air detected — skipped the trimmed "
                    "full-video export."
                )

            export_base = 63.0
            export_span = 8.0 if do_export else 0.0
            render_base = export_base + export_span
            render_span = (99.0 - render_base) / max(1, len(chosen))

            if do_export:
                self._check_cancel(job)
                job.set_stage("Removing dead air (full video export)", export_base)
                export_name = "full_active_only.mp4"
                try:
                    exported_dur = editor.render_active_only(
                        src, active_regions, outdir / export_name,
                        on_progress=job.stage_progress(export_base, export_span),
                        cancel_event=job.cancel_event,
                    )
                    job.exports.append({
                        "filename": export_name,
                        "url": f"/api/clips/{job.id}/{export_name}",
                        "duration": round(exported_dur, 1),
                        "label": "Full video with dead air removed",
                    })
                except ff.Cancelled:
                    raise
                except Exception as e:
                    job.warnings.append(f"Dead-air-removed export failed: {e}")

            opts = editor.RenderOptions(
                aspect=s["aspect"], vertical_mode=s["vertical_mode"],
                captions=bool(s["captions"]),
            )
            for i, cand in enumerate(chosen):
                self._check_cancel(job)
                if not cand.title:
                    cand.title = analyzer.default_title(cand, i)
                job.set_stage(
                    f"Rendering clip {i + 1}/{len(chosen)}: {cand.title}",
                    render_base + render_span * i)
                filename = f"clip_{i + 1:02d}.mp4"
                warnings = editor.render_clip(
                    src, cand, outdir / filename, opts,
                    on_progress=job.stage_progress(
                        render_base + render_span * i, render_span),
                    cancel_event=job.cancel_event,
                )
                for w in warnings:
                    if w not in job.warnings:
                        job.warnings.append(w)
                clip = cand.to_dict()
                clip["filename"] = filename
                clip["url"] = f"/api/clips/{job.id}/{filename}"
                job.clips.append(clip)
            if not job.clips:
                raise RuntimeError("No clips were rendered.")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _check_cancel(job: Job) -> None:
        if job.cancel_event.is_set():
            raise ff.Cancelled("job cancelled")
