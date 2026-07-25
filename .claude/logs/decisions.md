# Decision log

Append-only. See `.claude/CLAUDE.md` for the format and rules.

## 2026-07-08 09:00 — Scaffold the .claude/ agent constitution
**Plan:** Create `.claude/CLAUDE.md` (P1 reasoning + logging rules), `.claude/agents/researcher.md` (read-only, P2/P3 info gathering), and `.claude/agents/verifier.md` (read-only, P4 pre-ship check) so future tasks in this repo follow a plan → research → research → verify workflow.
**Phases used:** P1
**Outcome:** Added the three files plus this log. No P2-P4 needed — this was scaffolding the workflow itself, not a change it governs.

## 2026-07-25 00:41 — NiceClip: AI social-media video clipper for Windows
**Plan:** Build a local-first desktop app (Python + FastAPI web UI + ffmpeg) that ingests videos up to 15GB by path or streamed upload, finds highlight moments (audio energy, scene detection, faster-whisper transcription, heuristic scoring with optional Claude API ranking), and renders vertical 1080x1920 clips with burned-in captions and loudness normalization. Ship Windows install/build scripts (install.bat, PyInstaller) plus a GitHub Actions workflow that produces a downloadable Windows package.
**Phases used:** P1 P2 P4 (P3 folded into P1 empirical checks — researcher has no shell access, so ffmpeg capability questions were answered by direct testing)
**Outcome:** Shipped NiceClip under `niceclip/`: Python package (ffmpeg utils, analyzer, editor, Claude ranking, job queue, pipeline, FastAPI server, single-file web UI), Windows install/build scripts, and a GitHub Actions workflow producing a downloadable Windows zip. Smoke-tested end to end on a synthetic video: energy-based clip selection, 1080x1920 renders with audio, ASS caption burn-in, API upload→job→download round trip, traversal guard, graceful degradation without faster-whisper. One bug found and fixed during testing (np.float64 in job JSON). P4 verifier run recorded in a follow-up entry.
