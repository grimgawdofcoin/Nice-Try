"""The end-to-end job: probe → audio proxy → transcribe → (scenes) →
score → (Claude re-rank) → render clips.

Progress budget (of 100): probe 2, audio 10, transcribe 40, scenes 8,
scoring 2, rendering the rest.
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
}


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
            if info.has_audio:
                analyzer.extract_audio(
                    src, wav, info.duration,
                    on_progress=job.stage_progress(2, 10),
                    cancel_event=job.cancel_event,
                )
                job.set_stage("Analyzing audio energy", 12)
                analysis.energy = analyzer.compute_energy(wav)
            else:
                job.warnings.append("Video has no audio track — using visual/"
                                    "spacing heuristics only.")

            self._check_cancel(job)
            if s["transcribe"] and info.has_audio:
                job.set_stage(
                    f"Transcribing speech (Whisper {s['whisper_model']}) — "
                    "this is the slow part", 14)
                segments = analyzer.transcribe(
                    wav, info.duration, s["whisper_model"],
                    on_progress=job.stage_progress(14, 40),
                    cancel_event=job.cancel_event,
                )
                if segments is None:
                    job.warnings.append(
                        "faster-whisper is not installed — clips were chosen "
                        "by audio energy alone, and captions are unavailable."
                    )
                else:
                    analysis.segments = segments
                    analysis.transcript_available = True
            job.set_stage("Transcription done", 54)

            self._check_cancel(job)
            if s["scene_detection"]:
                job.set_stage("Detecting scene changes", 55)
                try:
                    analysis.scene_times = analyzer.detect_scenes(
                        src, cancel_event=job.cancel_event)
                except ff.Cancelled:
                    raise
                except Exception:
                    job.warnings.append("Scene detection failed; continuing "
                                        "without it.")

            job.set_stage("Scoring highlight candidates", 62)
            candidates = analyzer.build_candidates(
                analysis, min_len=s["min_len"], max_len=s["max_len"])
            if not candidates:
                raise RuntimeError("No usable clip candidates were found.")

            picked = None
            if s["ai_ranking"] and analysis.transcript_available:
                if llm.claude_available():
                    job.set_stage("AI ranking (Claude)", 63)
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
            opts = editor.RenderOptions(
                aspect=s["aspect"], vertical_mode=s["vertical_mode"],
                captions=bool(s["captions"]),
            )
            render_base = 65.0
            render_span = 34.0 / max(1, len(chosen))
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
