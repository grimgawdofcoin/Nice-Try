"""Locate and drive ffmpeg.

Everything that touches the ffmpeg binary lives here: discovery (bundled →
env → PATH → imageio-ffmpeg), media probing, capability detection (does this
build have libass?), filter-path escaping for Windows, and a subprocess
runner that reports progress and supports cancellation.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class FFmpegNotFound(RuntimeError):
    pass


def _candidate_paths() -> list[Path]:
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidates: list[Path] = []
    env = os.environ.get("NICECLIP_FFMPEG")
    if env:
        candidates.append(Path(env))
    # Frozen (PyInstaller) layout: ffmpeg shipped next to the executable.
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
        candidates += [base / "ffmpeg" / exe, base / exe, base / "_internal" / "ffmpeg" / exe]
    # Source layout: tools/ dir created by install_windows.bat at repo root.
    here = Path(__file__).resolve()
    for parent in [here.parent.parent, here.parent.parent.parent]:
        candidates.append(parent / "tools" / "ffmpeg" / exe)
    return candidates


def find_ffmpeg() -> str:
    for cand in _candidate_paths():
        if cand.is_file():
            return str(cand)
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise FFmpegNotFound(
        "ffmpeg not found. Install it (winget install Gyan.FFmpeg), run the "
        "NiceClip installer, pip install imageio-ffmpeg, or set NICECLIP_FFMPEG "
        "to the full path of ffmpeg.exe."
    )


_filters_cache: dict[str, set[str]] = {}


def available_filters(ffmpeg: str) -> set[str]:
    if ffmpeg in _filters_cache:
        return _filters_cache[ffmpeg]
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=30,
            creationflags=_CREATE_NO_WINDOW,
        ).stdout
        names = {line.split()[1] for line in out.splitlines() if len(line.split()) > 1}
    except Exception:
        names = set()
    _filters_cache[ffmpeg] = names
    return names


def has_filter(ffmpeg: str, name: str) -> bool:
    return name in available_filters(ffmpeg)


@dataclass
class MediaInfo:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    has_video: bool = False
    raw: str = field(default="", repr=False)


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Stream.*Video:.*?(\d{2,5})x(\d{2,5})")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")


def probe(path: str | Path) -> MediaInfo:
    """Parse `ffmpeg -i` stderr — avoids needing a separate ffprobe binary."""
    ffmpeg = find_ffmpeg()
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, errors="replace", timeout=120,
        creationflags=_CREATE_NO_WINDOW,
    )
    err = proc.stderr or ""
    info = MediaInfo(raw=err)
    m = _DUR_RE.search(err)
    if m:
        h, mnt, s = m.groups()
        info.duration = int(h) * 3600 + int(mnt) * 60 + float(s)
    v = _VIDEO_RE.search(err)
    if v:
        info.width, info.height = int(v.group(1)), int(v.group(2))
        info.has_video = True
        f = _FPS_RE.search(err)
        if f:
            info.fps = float(f.group(1))
    if "Audio:" in err:
        info.has_audio = True
    return info


def filter_path(path: str | Path) -> str:
    """Escape a filesystem path for use inside an ffmpeg filtergraph.

    Windows drive-letter colons collide with the filter option separator, so
    `C:\\x\\s.ass` must become `C\\:/x/s.ass` (and quotes get escaped).
    """
    p = str(Path(path).absolute()).replace("\\", "/")
    return p.replace(":", "\\:").replace("'", "\\'")


class Cancelled(RuntimeError):
    pass


def run_ffmpeg(
    args: list[str],
    *,
    total_duration: float = 0.0,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout: Optional[float] = None,
) -> None:
    """Run ffmpeg, streaming progress (fraction 0..1) via `-progress pipe:1`.

    Raises Cancelled if cancel_event fires, RuntimeError on nonzero exit.
    """
    ffmpeg = find_ffmpeg()
    cmd = [ffmpeg, "-hide_banner", "-y", *args, "-progress", "pipe:1", "-nostats"]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace", creationflags=_CREATE_NO_WINDOW,
    )
    stderr_tail: list[str] = []

    def _drain_stderr() -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            stderr_tail.append(line)
            if len(stderr_tail) > 60:
                del stderr_tail[0]

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled("ffmpeg cancelled")
            line = line.strip()
            if line.startswith("out_time_ms=") and total_duration > 0 and on_progress:
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000
                    on_progress(min(1.0, done / total_duration))
                except ValueError:
                    pass
        code = proc.wait(timeout=timeout)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    t.join(timeout=5)
    if code != 0:
        raise RuntimeError(
            "ffmpeg failed (exit %s):\n%s" % (code, "".join(stderr_tail[-25:]))
        )
    if on_progress:
        on_progress(1.0)


def parse_showinfo_times(stderr_text: str) -> list[float]:
    """Extract pts_time values from showinfo filter output (scene detection)."""
    return [float(m) for m in re.findall(r"pts_time:\s*([\d.]+)", stderr_text)]


def run_ffmpeg_capture_stderr(
    args: list[str],
    *,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Run ffmpeg and return full stderr (used for scene detection/showinfo)."""
    ffmpeg = find_ffmpeg()
    cmd = [ffmpeg, "-hide_banner", *args]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, errors="replace", creationflags=_CREATE_NO_WINDOW,
    )
    chunks: list[str] = []
    for line in proc.stderr:  # type: ignore[union-attr]
        if cancel_event is not None and cancel_event.is_set():
            proc.kill()
            proc.wait()
            raise Cancelled("ffmpeg cancelled")
        chunks.append(line)
    proc.wait()
    return "".join(chunks)
