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

## 2026-07-25 01:20 — NiceClip: P4 verification + Windows CI fix
**Plan:** Record the P4 verifier verdict on the NiceClip build and fix the failed Windows CI smoke test (frozen exe crashed: PyInstaller entry was niceclip/__main__.py, whose relative imports fail without package context).
**Phases used:** P1 P4
**Outcome:** P4 verifier returned PASS (no blockers; SDK usage verified against real anthropic/faster-whisper packages). Fixed CI by adding run.py launcher as the PyInstaller entry, made the CI smoke test capture app output and retry up to 2 min, and aligned pyproject deps with requirements.txt.

## 2026-07-25 06:40 — NiceClip: remove the 15 GB size limit
**Plan:** User correction: no file-size limit — must handle e.g. a 63 GB, 24-hour stream locally. Remove server/UI hard caps, add a free-disk-space guard on upload instead, bound the O(n^2) candidate dedupe for very long transcripts, update docs/UI copy.
**Phases used:** P1 P4
**Outcome:** Removed every size cap (server, job creation, UI, docs). Uploads now guarded by free disk space: upfront Content-Length check plus a re-check every 512 MB while streaming, returning HTTP 507 with a pointer to the zero-copy Browse path. Bounded candidate dedupe to O(n*40) so day-long transcripts score in milliseconds. P4 verifier initially FAILed on a stale docstring; fixed it plus a Content-Length parse guard, re-verified PASS.

## 2026-07-25 06:55 — NiceClip: dead-air detection and removal
**Plan:** User's real footage is ~2h of speech inside a 24h recording (forgot to stop). Add activity detection from the RMS energy track; transcribe only active regions (timestamps remapped) so 24h no longer means 24h of Whisper; restrict clip candidates to active regions; add an optional dead-air-free export (fast keyframe copy / precise re-encode) with UI + docs.
**Phases used:** P1 P4
**Outcome:** Shipped adaptive-threshold dead-air detection (analyzer.detect_active_regions), region-limited transcription with timestamp remapping, active-region candidate filtering, and an optional 'Cut dead air' full-video export (precise trim+concat re-encode, not keyframe-snapped). Tested on a synthetic video with real silent stretches (region detection, remap round-trip, full pipeline via direct call and via the live JobManager/server) plus a dedicated n=1-region ffmpeg filtergraph check. Found and fixed two real bugs during testing: -af/-filter_complex ffmpeg incompatibility in the export renderer, and an hours-only duration formatter that rounded short/human-scale durations to '0.0h'. P4 verifier ran the actual n=1 filtergraph against the shipped ffmpeg binary and returned PASS; one SHOULD-FIX (wrong sample-width divisor in build_trimmed_wav, inert on the current mono-only call site but fixed for correctness) applied post-verification.
