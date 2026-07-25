@echo off
setlocal enabledelayedexpansion
title NiceClip installer
echo.
echo  ============================================
echo    NiceClip - one-time Windows setup
echo  ============================================
echo.

rem Run from the repo's niceclip\ directory (parent of scripts\)
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python was not found on PATH.
    echo     Install Python 3.10+ from https://www.python.org/downloads/
    echo     IMPORTANT: tick "Add python.exe to PATH" in the installer.
    pause
    exit /b 1
)

echo [1/5] Creating virtual environment...
if not exist .venv (
    python -m venv .venv || (echo [!] venv creation failed & pause & exit /b 1)
)

echo [2/5] Installing Python dependencies (this can take a few minutes)...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt || (echo [!] pip install failed & pause & exit /b 1)

echo [3/5] Downloading ffmpeg (full build with caption support)...
if not exist tools\ffmpeg\ffmpeg.exe (
    mkdir tools 2>nul
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$ProgressPreference='SilentlyContinue';" ^
      "Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile 'tools\ffmpeg.zip';" ^
      "Expand-Archive -Force 'tools\ffmpeg.zip' 'tools\ffmpeg_tmp';" ^
      "$exe = Get-ChildItem 'tools\ffmpeg_tmp' -Recurse -Filter ffmpeg.exe | Select-Object -First 1;" ^
      "New-Item -ItemType Directory -Force 'tools\ffmpeg' | Out-Null;" ^
      "Copy-Item $exe.FullName 'tools\ffmpeg\ffmpeg.exe';" ^
      "Remove-Item -Recurse -Force 'tools\ffmpeg_tmp','tools\ffmpeg.zip'"
    if not exist tools\ffmpeg\ffmpeg.exe (
        echo [!] ffmpeg download failed. NiceClip will fall back to the
        echo     pip-installed ffmpeg, which may lack caption support.
    )
)

echo [4/5] Downloading speech-recognition models for offline use (one-time,
echo        several GB — safe to Ctrl+C and re-run later if you're in a hurry;
echo        transcription just won't work until this finishes)...
python scripts\download_whisper_models.py
if errorlevel 1 (
    echo [!] Whisper model download failed or was skipped. Transcription will
    echo     try to download models on first use instead ^(needs internet^).
)

echo [5/5] Creating launcher...
> NiceClip.bat (
    echo @echo off
    echo cd /d "%%~dp0"
    echo call .venv\Scripts\activate.bat
    echo python -m niceclip
    echo pause
)

echo.
echo  ============================================
echo    Done! Double-click NiceClip.bat to start.
echo    Your browser will open automatically.
echo  ============================================
echo.
echo  Optional: for AI clip selection, set your Claude API key once:
echo     setx ANTHROPIC_API_KEY "sk-ant-..."
echo.
pause
