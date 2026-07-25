@echo off
setlocal
title NiceClip - build Windows package
cd /d "%~dp0.."

where python >nul 2>nul || (echo [!] Python 3.10+ required on PATH & pause & exit /b 1)

if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller || (echo [!] install failed & pause & exit /b 1)

echo Downloading speech-recognition models for offline use (one-time, several GB)...
python scripts\download_whisper_models.py

echo Building NiceClip.exe (PyInstaller onedir - onefile is fragile with ctranslate2)...
pyinstaller --noconfirm --clean --onedir --name NiceClip ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all tokenizers ^
  --collect-all imageio_ffmpeg ^
  --add-data "niceclip\web;niceclip\web" ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on ^
  run.py || (echo [!] PyInstaller failed & pause & exit /b 1)

if exist tools\ffmpeg\ffmpeg.exe (
    mkdir dist\NiceClip\ffmpeg 2>nul
    copy /y tools\ffmpeg\ffmpeg.exe dist\NiceClip\ffmpeg\ >nul
    echo Bundled full ffmpeg build.
) else (
    echo [i] tools\ffmpeg\ffmpeg.exe not found - run scripts\install_windows.bat
    echo     first to bundle the full ffmpeg build with caption support.
)

if exist tools\whisper_models (
    xcopy /e /i /y tools\whisper_models dist\NiceClip\whisper_models >nul
    echo Bundled Whisper speech models for offline use.
) else (
    echo [i] tools\whisper_models not found - transcription will need internet
    echo     access on first use in this build.
)

echo.
echo Done. Distributable folder: dist\NiceClip  (run dist\NiceClip\NiceClip.exe)
pause
