@echo off
rem PersianAiKit - install the voice service (natural voices, voice cloning, sound of anything). Guide: VOICE-SETUP.md
rem Needs Python 3.10-3.13 (x64) in PATH and ~6 GB free disk. Safe to run again: it resumes and skips what is already there.
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul || (echo [!] Python not found. Install Python 3.11 x64 from python.org and tick "Add to PATH". & pause & exit /b 1)
if not exist "voice\.venv\Scripts\python.exe" (
  echo === 1/3  Python environment: voice\.venv
  python -m venv voice\.venv || (pause & exit /b 1)
)
echo === 2/3  Python packages (voice\requirements.txt)
"voice\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --retries 10 --timeout 60 -r voice\requirements.txt || (pause & exit /b 1)
echo === 3/3  Models (about 3.4 GB; interrupted downloads resume)
"voice\.venv\Scripts\python.exe" tools\download_voice_models.py --only pocket-fa,sa3-small-sfx,m2m100-ct2 %* || (pause & exit /b 1)
echo.
echo Done. Run Run-Server.bat - the kit starts the voice service by itself (sections 4, 5, 6 of the test page).
pause
