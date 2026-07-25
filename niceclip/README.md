# 🎬 NiceClip — AI video clipper for social media

Feed it a long video — a stream VOD, podcast, webinar, vlog, **any length,
any size** (a 63 GB, 24-hour stream is fine) — and NiceClip finds the moments
worth posting and renders them as finished clips: **vertical 9:16**,
**burned-in captions**, **loudness-normalized audio**, ranked by expected
short-form performance.

It's the same core loop as OpusClip/Klap-style tools, except it runs **entirely
on your own computer**: no upload to someone's cloud, no subscription, no
watermark.

## What it does

- **Dead-air detection** — if you left the recorder running (a 24-hour
  capture with 2 hours of actual talking is a normal case), NiceClip finds
  the silent stretches from the audio track automatically. Only the active
  parts get transcribed and considered for clips — so 24 hours of tape
  doesn't mean 24 hours of Whisper. Turn on *Cut dead air* to also get a
  single clean export with the silence spliced out.
- **Highlight detection** — transcribes speech locally (faster-whisper),
  scores every possible clip window using hook phrases, questions, humor,
  audio-energy spikes, and (optionally) scene-cut density.
- **AI clip selection (optional)** — with a Claude API key set, Claude
  re-ranks the top candidates, writes a punchy title for each clip, and
  explains why it will hold attention. Without a key, a built-in heuristic
  ranker takes over — everything still works.
- **Auto reframe** — vertical 9:16 with a blurred background (or center-crop),
  square 1:1, or original aspect.
- **Captions** — word-grouped, bold, burned-in subtitles generated from
  Whisper word timestamps.
- **No size limit** — video is streamed through ffmpeg, so even a multi-day,
  60+ GB recording never touches RAM. Point NiceClip at a file already on
  disk (Browse) and nothing is copied at all; uploads are only bounded by
  your free disk space.
- **Local web UI** — drag-drop or browse, watch progress per stage, preview
  every clip in the browser, download with one click.

## Install on Windows

### Option A — download the ready-made app (easiest)

1. Go to this repo's **Actions** tab → latest **Build NiceClip for Windows**
   run → download the **NiceClip-windows** artifact (on tagged releases it's
   also attached to the GitHub Release).
2. Unzip anywhere (e.g. `C:\NiceClip`).
3. Double-click **`NiceClip.exe`**. Your browser opens the app at
   `http://127.0.0.1:8765`.

No Python, no ffmpeg, no internet connection required — everything is
bundled, including a full ffmpeg build with caption support and the Whisper
speech-recognition models (so transcription works fully offline too).

### Option B — install from source

1. Install [Python 3.10+](https://www.python.org/downloads/) (tick
   *"Add python.exe to PATH"*).
2. Download/clone this repo, open the `niceclip` folder.
3. Double-click **`scripts\install_windows.bat`** — it sets up a private
   Python environment and downloads ffmpeg.
4. Double-click the **`NiceClip.bat`** it creates.

### Option C — pip (any OS)

```bash
cd niceclip
pip install .
niceclip            # opens http://127.0.0.1:8765
```

You'll also want a real ffmpeg on PATH (`winget install Gyan.FFmpeg`,
`brew install ffmpeg`, or `apt install ffmpeg`) — the pip-installed fallback
(imageio-ffmpeg) works but its build may lack the caption filter.

## Enable AI clip selection (optional but recommended)

NiceClip uses Claude to pick and title the best clips. Set your API key once
(get one at <https://platform.claude.com/>):

```bat
setx ANTHROPIC_API_KEY "sk-ant-..."
```

Restart NiceClip afterwards. The "AI ranking on" badge in the header confirms
it's active. Only short transcript excerpts of candidate segments are sent to
the API — never the video or audio itself.

## Using it

1. **Pick a video** — drag-drop to upload (streams straight to disk), or
   click *Browse…* and select a file already on your machine (zero copying —
   the best option for huge files).
2. **Tune settings** — number of clips, length range, format, captions,
   transcription quality.
3. **Create clips** — watch the stages: audio extraction → transcription →
   scoring → AI ranking → rendering. Transcription is the slow part; budget
   roughly ¼–½ of the video's runtime on a typical CPU with the default
   *Balanced* model. For day-long streams pick *Fastest* (tiny) — a 24-hour
   VOD can otherwise take most of a workday to transcribe on CPU.
4. **Preview & download** — every clip appears with its title, score, and the
   reason it was picked. Files also land in `%USERPROFILE%\NiceClip\clips`.

## How it compares to the paid tools

| | NiceClip | OpusClip / Klap / Vizard |
|---|---|---|
| Auto highlight detection | ✅ local Whisper + heuristics + Claude | ✅ cloud |
| Virality-style scoring + reasons | ✅ | ✅ |
| Vertical reframe + captions | ✅ blur-pad / crop, burned-in captions | ✅ incl. face tracking |
| File size limit | none — local, no upload wait | typically 2–10 GB cloud upload |
| Privacy | video never leaves your machine | uploaded to their cloud |
| Price | free, bring-your-own Claude key (optional) | subscription |
| Speaker face tracking, auto-post/scheduling, B-roll | ❌ not yet (roadmap) | ✅ |

## Troubleshooting

- **"ffmpeg missing" badge** — run `scripts\install_windows.bat`, or
  `winget install Gyan.FFmpeg`, or set `NICECLIP_FFMPEG` to the full path of
  `ffmpeg.exe`.
- **"no captions" badge** — your ffmpeg build lacks libass. The installer's
  ffmpeg (and the packaged app's) includes it; `winget install Gyan.FFmpeg`
  also works. Clips still render, just without captions.
- **"no transcription" badge** — `pip install faster-whisper` into the same
  environment. Without it, clips are chosen by audio energy alone.
- **The downloadable Windows package ships its speech-recognition models
  offline** — transcription never needs internet access there. If you
  installed from source instead, the first use of each quality level (tiny/
  base/small/medium) downloads its model from Hugging Face once; run
  `scripts\download_whisper_models.py` ahead of time to fetch all of them, or
  just re-run `scripts\install_windows.bat`. If that download can't reach
  huggingface.co (blocked network, offline machine), NiceClip no longer fails
  the job — it warns and falls back to audio-energy-only clip selection
  automatically.
- Outputs, uploads and logs live in `%USERPROFILE%\NiceClip` (override with
  the `NICECLIP_DATA` environment variable).

## Development

```bash
cd niceclip
pip install -e . && niceclip --no-browser
```

`scripts\build_windows.bat` produces the same standalone `dist\NiceClip`
folder the CI workflow ships.
