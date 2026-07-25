"""Render selected moments into finished social clips.

Each clip is cut frame-accurately, reframed (vertical 9:16 with blurred
background or center-crop, square, or original), loudness-normalized to
-14 LUFS (platform standard), and captioned with burned-in word-group
subtitles generated from Whisper word timestamps.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import ffmpeg_utils as ff
from .analyzer import Candidate, Word

ProgressFn = Callable[[float], None]

MAX_CAPTION_WORDS = 4
MAX_CAPTION_SECONDS = 2.6
CAPTION_GAP_BREAK = 1.0


@dataclass
class RenderOptions:
    aspect: str = "vertical"          # vertical | square | original
    vertical_mode: str = "fit"        # fit (blur pad) | crop (center crop)
    captions: bool = True
    video_quality_crf: int = 20
    preset: str = "veryfast"


def output_dims(opts: RenderOptions) -> tuple[int, int]:
    if opts.aspect == "vertical":
        return 1080, 1920
    if opts.aspect == "square":
        return 1080, 1080
    return 0, 0  # original: keep source dims


def _fmt_ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs == 100:
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(
    words: list[Word],
    clip_start: float,
    clip_end: float,
    play_w: int = 1080,
    play_h: int = 1920,
) -> Optional[str]:
    """Group word timestamps into short punchy caption events. Returns the
    .ass document, or None when there are no words inside the clip."""
    inside = [w for w in words if w.end > clip_start + 0.05 and w.start < clip_end - 0.05]
    if not inside:
        return None

    font_size = max(40, int(play_h * 0.042))
    margin_v = int(play_h * 0.26) if play_h > play_w else int(play_h * 0.12)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,Arial,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,1,0,1,4,1,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    group: list[Word] = []

    def flush() -> None:
        if not group:
            return
        start = max(0.0, group[0].start - clip_start)
        end = min(clip_end - clip_start, group[-1].end - clip_start + 0.15)
        if end <= start:
            group.clear()
            return
        text = _ass_escape(" ".join(w.text.strip() for w in group).strip().upper())
        events.append(
            f"Dialogue: 0,{_fmt_ass_time(start)},{_fmt_ass_time(end)},Pop,,0,0,0,,{text}"
        )
        group.clear()

    for w in inside:
        if group:
            span = w.end - group[0].start
            gap = w.start - group[-1].end
            if (len(group) >= MAX_CAPTION_WORDS or span > MAX_CAPTION_SECONDS
                    or gap > CAPTION_GAP_BREAK):
                flush()
        group.append(w)
    flush()
    if not events:
        return None
    return header + "\n".join(events) + "\n"


def _build_video_filter(
    opts: RenderOptions, ass_path: Optional[Path]
) -> Optional[str]:
    parts: list[str] = []
    if opts.aspect == "vertical" and opts.vertical_mode == "fit":
        parts.append(
            "split=2[bga][fga];"
            "[bga]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=luma_radius=25:luma_power=2,"
            "eq=brightness=-0.08[bg];"
            "[fga]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
    elif opts.aspect == "vertical":
        parts.append(
            "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920,setsar=1"
        )
    elif opts.aspect == "square":
        parts.append("crop='min(iw,ih)':'min(iw,ih)',scale=1080:1080,setsar=1")
    if ass_path is not None:
        parts.append(f"subtitles='{ff.filter_path(ass_path)}'")
    if not parts:
        return None
    return ",".join(parts)


def render_clip(
    src: str | Path,
    candidate: Candidate,
    out_path: str | Path,
    opts: RenderOptions,
    on_progress: Optional[ProgressFn] = None,
    cancel_event: Optional[threading.Event] = None,
) -> list[str]:
    """Render one clip. Returns a list of warnings (e.g. caption fallback)."""
    warnings: list[str] = []
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = candidate.duration

    ass_path: Optional[Path] = None
    if opts.captions and candidate.words:
        w, h = output_dims(opts)
        if w == 0:
            info = ff.probe(src)
            w, h = (info.width or 1920), (info.height or 1080)
        ass_doc = build_ass(candidate.words, candidate.start, candidate.end, w, h)
        if ass_doc:
            ffmpeg = ff.find_ffmpeg()
            if ff.has_filter(ffmpeg, "subtitles"):
                ass_path = out_path.with_suffix(".ass")
                ass_path.write_text(ass_doc, encoding="utf-8")
            else:
                warnings.append(
                    "This ffmpeg build lacks the subtitles filter (libass); "
                    "clip rendered without captions. Install a full ffmpeg "
                    "build (winget install Gyan.FFmpeg)."
                )

    def _attempt(with_captions: bool) -> None:
        vf = _build_video_filter(opts, ass_path if with_captions else None)
        args = ["-ss", f"{candidate.start:.3f}", "-i", str(src),
                "-t", f"{duration:.3f}"]
        if vf:
            args += ["-vf", vf]
        args += [
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-preset", opts.preset,
            "-crf", str(opts.video_quality_crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(out_path),
        ]
        ff.run_ffmpeg(args, total_duration=duration,
                      on_progress=on_progress, cancel_event=cancel_event)

    try:
        _attempt(with_captions=ass_path is not None)
    except ff.Cancelled:
        raise
    except RuntimeError:
        if ass_path is None:
            raise
        # Caption burn-in is the most environment-sensitive step; retry bare.
        warnings.append(
            "Caption burn-in failed on this ffmpeg build; clip rendered "
            "without captions."
        )
        _attempt(with_captions=False)
    finally:
        if ass_path is not None and ass_path.exists():
            try:
                ass_path.unlink()
            except OSError:
                pass
    return warnings
