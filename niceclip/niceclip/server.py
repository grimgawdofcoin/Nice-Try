"""Local web server: serves the UI and the job/upload/clip API.

Binds to 127.0.0.1 — NiceClip is a desktop app that happens to use the
browser as its UI, not a hosted service.
"""

from __future__ import annotations

import os
import re
import string
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import __version__, ffmpeg_utils as ff, llm
from .jobs import JobManager
from .pipeline import DEFAULT_SETTINGS, PipelineRunner

MAX_UPLOAD_BYTES = 16 * 1024 ** 3  # a hair over the advertised 15 GB
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts", ".mts",
              ".wmv", ".flv", ".mpg", ".mpeg", ".3gp"}


def data_root() -> Path:
    root = os.environ.get("NICECLIP_DATA")
    base = Path(root) if root else Path.home() / "NiceClip"
    for sub in ("uploads", "clips", "work"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def create_app() -> FastAPI:
    base = data_root()
    uploads = base / "uploads"
    clips_root = base / "clips"
    work_root = base / "work"

    app = FastAPI(title="NiceClip", version=__version__)
    manager = JobManager(PipelineRunner(clips_root, work_root))
    index_html = (Path(__file__).parent / "web" / "index.html").read_text(
        encoding="utf-8")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return index_html

    @app.get("/api/health")
    def health() -> dict:
        try:
            ffmpeg = ff.find_ffmpeg()
            ffmpeg_ok, subtitles_ok = True, ff.has_filter(ffmpeg, "subtitles")
        except ff.FFmpegNotFound:
            ffmpeg, ffmpeg_ok, subtitles_ok = None, False, False
        try:
            import faster_whisper  # noqa: F401
            whisper_ok = True
        except ImportError:
            whisper_ok = False
        return {
            "app": "NiceClip",
            "version": __version__,
            "ffmpeg": ffmpeg_ok,
            "ffmpeg_path": ffmpeg,
            "captions": subtitles_ok,
            "whisper": whisper_ok,
            "ai_ranking": llm.claude_available(),
            "data_dir": str(base),
            "defaults": DEFAULT_SETTINGS,
        }

    @app.post("/api/upload")
    async def upload(request: Request, filename: str = "video.mp4") -> dict:
        safe = re.sub(r"[^\w.\- ]", "_", Path(filename).name).strip() or "video.mp4"
        dest = uploads / safe
        stem, suffix, n = dest.stem, dest.suffix, 1
        while dest.exists():
            dest = uploads / f"{stem}_{n}{suffix}"
            n += 1
        size = 0
        try:
            with open(dest, "wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "File exceeds the 15 GB limit")
                    f.write(chunk)
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        if size == 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "Empty upload")
        return {"path": str(dest), "bytes": size}

    @app.post("/api/jobs")
    async def create_job(payload: dict) -> dict:
        source = str(payload.get("source", "")).strip()
        if not source:
            raise HTTPException(400, "Missing 'source' (path to a video file)")
        src = Path(source)
        if not src.is_file():
            raise HTTPException(400, f"File not found: {source}")
        if src.stat().st_size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File exceeds the 15 GB limit")
        job = manager.submit(str(src), payload.get("settings") or {})
        return job.snapshot()

    @app.get("/api/jobs")
    def list_jobs() -> list[dict]:
        return [j.snapshot() for j in manager.all()]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "No such job")
        return job.snapshot()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        if not manager.cancel(job_id):
            raise HTTPException(409, "Job cannot be cancelled")
        return {"ok": True}

    @app.get("/api/clips/{job_id}/{filename}")
    def get_clip(job_id: str, filename: str):
        path = (clips_root / job_id / filename).resolve()
        if clips_root.resolve() not in path.parents or not path.is_file():
            raise HTTPException(404, "Clip not found")
        return FileResponse(path, media_type="video/mp4", filename=filename)

    @app.get("/api/browse")
    def browse(path: str = "") -> JSONResponse:
        """Minimal local file browser so users can pick a video without
        copying it. Local app, local disk."""
        if not path:
            if sys.platform == "win32":
                drives = [f"{d}:\\" for d in string.ascii_uppercase
                          if Path(f"{d}:\\").exists()]
                entries = [{"name": d, "path": d, "dir": True} for d in drives]
                return JSONResponse({"path": "", "parent": None,
                                     "entries": entries})
            path = str(Path.home())
        p = Path(path)
        if not p.is_dir():
            raise HTTPException(400, "Not a directory")
        entries = []
        try:
            for child in sorted(p.iterdir(),
                                key=lambda c: (not c.is_dir(), c.name.lower())):
                if child.name.startswith("."):
                    continue
                try:
                    if child.is_dir():
                        entries.append({"name": child.name, "path": str(child),
                                        "dir": True})
                    elif child.suffix.lower() in VIDEO_EXTS:
                        entries.append({"name": child.name, "path": str(child),
                                        "dir": False,
                                        "size": child.stat().st_size})
                except OSError:
                    continue
        except PermissionError:
            raise HTTPException(403, "Permission denied")
        parent = str(p.parent) if p.parent != p else ("" if sys.platform == "win32" else None)
        return JSONResponse({"path": str(p), "parent": parent,
                             "entries": entries[:500]})

    return app
