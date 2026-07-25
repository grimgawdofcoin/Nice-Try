"""Find the moments worth clipping.

The analysis pipeline never loads the source video into memory — ffmpeg
streams it. Signals used, in order of weight:

1. Speech transcript (faster-whisper, optional): sentence boundaries, hook
   phrases, questions, laughter.
2. Audio energy: RMS loudness per window from a 16 kHz mono proxy WAV.
3. Scene cuts (optional, slower): ffmpeg scene-change detection.

Candidates are transcript-aligned windows (or energy peaks when there is no
speech), scored heuristically; `llm.rank_with_claude` can then re-rank them.
"""

from __future__ import annotations

import re
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import ffmpeg_utils as ff

ProgressFn = Callable[[float], None]

ENERGY_WINDOW_S = 0.5

# Phrases that historically correlate with retention hooks on short-form video.
HOOK_PATTERNS = [
    r"\bsecret\b", r"\bnobody\b", r"\beveryone\b", r"\bnever\b", r"\balways\b",
    r"\bhow to\b", r"\bwhy\b", r"\bmistake", r"\bwrong\b", r"\btruth\b",
    r"\bcrazy\b", r"\binsane\b", r"\bunbelievable\b", r"\bactually\b",
    r"\bfree\b", r"\bmoney\b", r"\bbest\b", r"\bworst\b", r"\bhack\b",
    r"\btrick\b", r"\bstop doing\b", r"\bhere'?s the thing\b", r"\blisten\b",
    r"\bimagine\b", r"\bwhat if\b", r"\bthe problem\b", r"\bchanged my\b",
    r"\bnumber one\b", r"\btop \d+\b", r"\bdon'?t\b.*\buntil\b",
]
_HOOK_RES = [re.compile(p, re.IGNORECASE) for p in HOOK_PATTERNS]
_LAUGH_RE = re.compile(r"\b(ha(ha)+|lol|laugh)", re.IGNORECASE)


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Candidate:
    start: float
    end: float
    text: str
    score: float = 0.0
    reason: str = ""
    title: str = ""
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        # float() casts: energy-path candidates carry numpy scalars, which
        # json.dumps rejects.
        return {
            "start": round(float(self.start), 2),
            "end": round(float(self.end), 2),
            "duration": round(float(self.duration), 2),
            "text": self.text,
            "score": round(float(self.score), 1),
            "reason": self.reason,
            "title": self.title,
        }


@dataclass
class Analysis:
    duration: float
    segments: list[Segment] = field(default_factory=list)
    energy: Optional[np.ndarray] = None
    scene_times: list[float] = field(default_factory=list)
    transcript_available: bool = False
    # (start, end) regions with real audio activity, on the ORIGINAL video's
    # timeline. Empty list means detection didn't run (no audio) — treat
    # everything as active. A populated list always excludes dead air; it
    # covers [0, duration] whole when nothing needed excluding.
    active_regions: list[tuple[float, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def extract_audio(
    src: str | Path,
    wav_path: str | Path,
    duration: float,
    on_progress: Optional[ProgressFn] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    # 16 kHz mono s16 ≈ 115 MB/hour, so even a 24 h stream is a ~2.8 GB proxy
    # (the 4 GB WAV format ceiling is reached around 37 h of footage).
    ff.run_ffmpeg(
        ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
         "-f", "wav", str(wav_path)],
        total_duration=duration,
        on_progress=on_progress,
        cancel_event=cancel_event,
    )


def compute_energy(wav_path: str | Path) -> np.ndarray:
    """Raw RMS energy (int16 scale) per ENERGY_WINDOW_S window."""
    with wave.open(str(wav_path), "rb") as w:
        rate = w.getframerate()
        win = int(rate * ENERGY_WINDOW_S)
        rms: list[float] = []
        while True:
            frames = w.readframes(win)
            if not frames:
                break
            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
            if samples.size == 0:
                break
            rms.append(float(np.sqrt(np.mean(samples ** 2))))
    return np.array(rms)


def normalize_energy(raw_rms: np.ndarray) -> np.ndarray:
    """Scale raw RMS to 0..1 for scoring."""
    if raw_rms.size == 0:
        return raw_rms
    peak = np.percentile(raw_rms, 98) or 1.0
    return np.clip(raw_rms / peak, 0.0, 1.0)


def detect_active_regions(
    raw_rms: np.ndarray,
    duration: float,
    *,
    abs_threshold: float = 100.0,
    pad: float = 0.75,
    merge_gap: float = 3.0,
    min_region: float = 1.5,
) -> list[tuple[float, float]]:
    """Find stretches with real audio activity (speech/action) vs dead air.

    The threshold adapts to the recording's noise floor but is capped
    relative to its loud level, so both quiet rooms and hissy mics work.
    Returns [] when the whole recording is effectively silent.
    """
    if raw_rms.size == 0:
        return [(0.0, duration)]
    floor = float(np.percentile(raw_rms, 10))
    loud = float(np.percentile(raw_rms, 95))
    if loud < abs_threshold:
        return []
    thresh = max(abs_threshold, floor * 3.0)
    thresh = min(thresh, max(abs_threshold, loud * 0.25))
    active = raw_rms > thresh
    if not active.any():
        return []

    regions: list[tuple[float, float]] = []
    start_idx: Optional[int] = None
    for i, on in enumerate(active):
        if on and start_idx is None:
            start_idx = i
        elif not on and start_idx is not None:
            regions.append((start_idx * ENERGY_WINDOW_S, i * ENERGY_WINDOW_S))
            start_idx = None
    if start_idx is not None:
        regions.append((start_idx * ENERGY_WINDOW_S, raw_rms.size * ENERGY_WINDOW_S))

    padded = [(max(0.0, s - pad), min(duration, e + pad)) for s, e in regions]
    merged: list[tuple[float, float]] = []
    for s, e in padded:
        if merged and s - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return [(s, e) for s, e in merged if e - s >= min_region]


def regions_duration(regions: list[tuple[float, float]]) -> float:
    return sum(e - s for s, e in regions)


def build_trimmed_wav(
    wav_path: str | Path,
    regions: list[tuple[float, float]],
    out_path: str | Path,
) -> None:
    """Concatenate the active regions of the proxy WAV into a shorter WAV so
    transcription only sees real content (24 h of tape, 2 h of speech →
    2 h of Whisper)."""
    with wave.open(str(wav_path), "rb") as src, wave.open(str(out_path), "wb") as dst:
        dst.setparams(src.getparams())
        rate = src.getframerate()
        total = src.getnframes()
        bytes_per_frame = src.getsampwidth() * src.getnchannels()
        chunk = rate * 60
        for s, e in regions:
            pos = min(total, int(s * rate))
            end = min(total, int(e * rate))
            src.setpos(pos)
            remaining = end - pos
            while remaining > 0:
                frames = src.readframes(min(chunk, remaining))
                if not frames:
                    break
                dst.writeframes(frames)
                remaining -= len(frames) // bytes_per_frame


def remap_time(t: float, regions: list[tuple[float, float]]) -> float:
    """Map a timestamp on the trimmed (concatenated-regions) timeline back to
    the original video timeline."""
    acc = 0.0
    for s, e in regions:
        d = e - s
        if t <= acc + d:
            return s + max(0.0, t - acc)
        acc += d
    return regions[-1][1] if regions else t


def remap_segments(
    segments: list[Segment], regions: list[tuple[float, float]]
) -> list[Segment]:
    out: list[Segment] = []
    for seg in segments:
        words = [Word(w.text, remap_time(w.start, regions),
                      remap_time(w.end, regions)) for w in seg.words]
        out.append(Segment(remap_time(seg.start, regions),
                           remap_time(seg.end, regions), seg.text, words))
    return out


def detect_scenes(
    src: str | Path,
    cancel_event: Optional[threading.Event] = None,
    threshold: float = 0.30,
) -> list[float]:
    """Scene-change timestamps. Decodes the whole video (downscaled) — slow on
    huge files, which is why it's an opt-in setting."""
    stderr = ff.run_ffmpeg_capture_stderr(
        ["-i", str(src), "-an",
         "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo",
         "-f", "null", "-"],
        cancel_event=cancel_event,
    )
    return ff.parse_showinfo_times(stderr)


def transcribe(
    wav_path: str | Path,
    duration: float,
    model_size: str = "small",
    on_progress: Optional[ProgressFn] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[list[Segment]]:
    """Transcribe with faster-whisper. Returns None when unavailable so the
    pipeline can degrade to audio-energy-only analysis."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return None
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    seg_iter, _info = model.transcribe(
        str(wav_path), vad_filter=True, word_timestamps=True, beam_size=1,
    )
    segments: list[Segment] = []
    for s in seg_iter:
        if cancel_event is not None and cancel_event.is_set():
            raise ff.Cancelled("transcription cancelled")
        words = [Word(w.word, w.start, w.end) for w in (s.words or [])]
        segments.append(Segment(s.start, s.end, s.text.strip(), words))
        if on_progress and duration > 0:
            on_progress(min(1.0, s.end / duration))
    if on_progress:
        on_progress(1.0)
    return segments


def _energy_at(analysis: Analysis, start: float, end: float) -> float:
    if analysis.energy is None or analysis.energy.size == 0:
        return 0.5
    i0 = max(0, int(start / ENERGY_WINDOW_S))
    i1 = min(analysis.energy.size, max(i0 + 1, int(end / ENERGY_WINDOW_S)))
    return float(np.mean(analysis.energy[i0:i1]))


def _text_score(text: str) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    hooks = sum(1 for rx in _HOOK_RES if rx.search(text))
    if hooks:
        score += min(3.0, hooks * 1.0)
        reasons.append(f"{hooks} hook phrase{'s' if hooks > 1 else ''}")
    q = text.count("?")
    if q:
        score += min(1.5, q * 0.75)
        reasons.append("poses a question")
    ex = text.count("!")
    if ex:
        score += min(1.0, ex * 0.5)
        reasons.append("high emphasis")
    if _LAUGH_RE.search(text):
        score += 1.0
        reasons.append("humor")
    return score, reasons


def _active_overlap_fraction(analysis: Analysis, start: float, end: float) -> float:
    """Fraction of [start, end) that falls inside a detected active region.
    1.0 when no active-region filtering is in effect."""
    regions = analysis.active_regions
    total = end - start
    if not regions or total <= 0:
        return 1.0
    covered = sum(max(0.0, min(end, e) - max(start, s)) for s, e in regions)
    return covered / total


def build_candidates(
    analysis: Analysis,
    min_len: float = 15.0,
    max_len: float = 60.0,
    max_candidates: int = 40,
) -> list[Candidate]:
    if analysis.transcript_available and analysis.segments:
        cands = _candidates_from_transcript(analysis, min_len, max_len)
    else:
        cands = _candidates_from_energy(analysis, min_len, max_len)
    # Drop windows that are mostly dead air (e.g. a forgot-to-stop recording
    # with hours of near-silence). No-op when the whole video is "active".
    if analysis.active_regions:
        active = [c for c in cands
                 if _active_overlap_fraction(analysis, c.start, c.end) >= 0.5]
        if active:
            cands = active
    _score_candidates(analysis, cands)
    cands.sort(key=lambda c: c.score, reverse=True)
    return _dedupe(cands, max_keep=max_candidates)


def _candidates_from_transcript(
    analysis: Analysis, min_len: float, max_len: float
) -> list[Candidate]:
    """Sliding grouping of consecutive segments into clip-sized windows,
    starting a new window at each segment so hooks can open a clip."""
    segs = analysis.segments
    cands: list[Candidate] = []
    for i in range(len(segs)):
        start = segs[i].start
        j = i
        while j < len(segs) and segs[j].end - start <= max_len:
            j += 1
        j = max(i + 1, j)
        window = segs[i:j]
        end = window[-1].end
        if end - start < min_len:
            # Too short even after absorbing everything in range — extend to
            # min_len if the video allows, else skip tail fragments.
            end = min(analysis.duration, start + min_len)
            if end - start < min_len * 0.6:
                continue
        text = " ".join(s.text for s in window).strip()
        words = [w for s in window for w in s.words]
        cands.append(Candidate(start=start, end=end, text=text, words=words))
    return cands


def _candidates_from_energy(
    analysis: Analysis, min_len: float, max_len: float
) -> list[Candidate]:
    """No transcript: rank fixed windows centered on loudness peaks."""
    e = analysis.energy
    if e is None or e.size == 0:
        # Nothing to go on: evenly spaced windows.
        length = min(max_len, max(min_len, 30.0))
        step = max(length, analysis.duration / 12)
        out = []
        t = 0.0
        while t + min_len <= analysis.duration:
            out.append(Candidate(start=t, end=min(t + length, analysis.duration), text=""))
            t += step
        return out
    length = min(max_len, max(min_len, 30.0))
    win = int(length / ENERGY_WINDOW_S)
    if e.size <= win:
        return [Candidate(start=0.0, end=min(analysis.duration, length), text="")]
    kernel = np.ones(win) / win
    rolling = np.convolve(e, kernel, mode="valid")
    order = np.argsort(rolling)[::-1]
    out: list[Candidate] = []
    used: list[tuple[float, float]] = []
    for idx in order:
        start = float(idx) * ENERGY_WINDOW_S
        end = min(start + length, analysis.duration)
        if any(not (end <= s or start >= t) for s, t in used):
            continue
        used.append((start, end))
        out.append(Candidate(start=start, end=end, text=""))
        if len(out) >= 24:
            break
    return out


def _score_candidates(analysis: Analysis, cands: list[Candidate]) -> None:
    for c in cands:
        reasons: list[str] = []
        energy = _energy_at(analysis, c.start, c.end)
        score = energy * 3.0
        if energy > 0.65:
            reasons.append("high audio energy")
        tscore, treasons = _text_score(c.text)
        score += tscore
        reasons += treasons
        if analysis.scene_times:
            cuts = sum(1 for t in analysis.scene_times if c.start <= t <= c.end)
            per_min = cuts / max(c.duration / 60.0, 0.1)
            if per_min >= 4:
                score += 1.0
                reasons.append("visually dynamic")
        # Slight penalty for the very beginning (intros) and very end (outros).
        if analysis.duration > 120:
            if c.start < 10:
                score -= 0.5
            if c.end > analysis.duration - 10:
                score -= 0.5
        # Prefer clips that fill a healthy share of the allowed range.
        c.score = max(0.0, score) * 10.0
        c.reason = ", ".join(reasons) if reasons else "steady segment"


def _dedupe(cands: list[Candidate], max_keep: int = 40,
            max_overlap: float = 0.5) -> list[Candidate]:
    """Greedy non-max suppression by overlap fraction (candidates pre-sorted
    by score). Stops at max_keep so a day-long transcript (tens of thousands
    of windows) stays O(n * max_keep) instead of quadratic."""
    kept: list[Candidate] = []
    for c in cands:
        ok = True
        for k in kept:
            inter = max(0.0, min(c.end, k.end) - max(c.start, k.start))
            if inter / max(1e-6, min(c.duration, k.duration)) > max_overlap:
                ok = False
                break
        if ok:
            kept.append(c)
            if len(kept) >= max_keep:
                break
    return kept


def default_title(c: Candidate, index: int) -> str:
    text = c.text.strip()
    if not text:
        return f"Highlight {index + 1}"
    words = text.split()
    title = " ".join(words[:8])
    return (title + "…") if len(words) > 8 else title
