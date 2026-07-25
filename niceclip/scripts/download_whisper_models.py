"""Pre-download faster-whisper (CTranslate2) speech models for fully offline
use. Run once before packaging NiceClip (or via install_windows.bat) so the
app never has to reach huggingface.co at runtime — matches how ffmpeg is
bundled rather than expected on the user's machine.

Models land in tools/whisper_models/<size>/, which niceclip.analyzer looks
for automatically (see analyzer._find_bundled_whisper_model).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Must stay in sync with the "Transcription quality" <select> in
# niceclip/web/index.html — a size offered there but missing here would fall
# back to a runtime download, which is exactly the failure this bundling
# exists to prevent. ~2.2 GB combined; adding "large" would roughly double it.
MODEL_SIZES = ["tiny", "base", "small", "medium"]


def main() -> int:
    try:
        from faster_whisper.utils import download_model
    except ImportError:
        print("faster-whisper is not installed — run `pip install -r "
              "requirements.txt` first.", file=sys.stderr)
        return 1

    root = Path(__file__).resolve().parent.parent  # niceclip/
    dest_root = root / "tools" / "whisper_models"
    dest_root.mkdir(parents=True, exist_ok=True)

    for size in MODEL_SIZES:
        dest = dest_root / size
        if (dest / "model.bin").is_file():
            print(f"[skip] {size} already downloaded at {dest}")
            continue
        print(f"[download] {size} -> {dest}")
        download_model(size, output_dir=str(dest))

    print("Done. Whisper models are ready for fully offline use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
