@echo off
title NMarketing - photo matting models
rem ================================================================
rem  NMarketing processing node - install the three photo-matting models (agent 2.7).
rem  u2netp (5 MB), IS-Net general use (170 MB) and BiRefNet-lite (220 MB; the photo kit's own file) cut the subject out of a photo;
rem  they run ONLY on this computer. Safe to run again: finished files are skipped, broken downloads continue where they stopped.
rem  If no Python here has onnxruntime yet, a small environment of its own is made first (onnxruntime-directml + numpy + Pillow,
rem  ~60 MB, uses the GPU through DirectML); a Python that already has onnxruntime is used as it is - nothing is installed twice.
rem  The panel's «دانلود» (scheduled for the night by default) does the same thing; this file is the manual way.
rem
rem    Install-Matting.bat                   runtime (only if needed) + the three models
rem    Install-Matting.bat --list            what is still missing
rem    Test-Matting.bat                      time every installed model on a test picture
rem  Log: logs\download-models.log in the data folder
rem ================================================================
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
  echo [!] Python was not found. Install Python 3.10+ from python.org and tick "Add python to PATH".
  pause
  exit /b 1
)
set "ONLY=--only matting-u2netp --only matting-isnet --only photo-background"
%PY% "%~dp0photo_matting.py" status --runtime-ok >nul 2>nul
if errorlevel 1 (
  echo No Python on this computer has onnxruntime yet - a small environment of its own will be made first.
  set "ONLY=--only matting-runtime %ONLY%"
) else (
  echo A Python with onnxruntime is already here - nothing to install for it.
)
%PY% "%~dp0download_models.py" --yes %ONLY% %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo Finished. Run Test-Matting.bat to try the models, and restart START.bat so the site sees them.
) else (
  echo Finished with problems - read the summary above, or logs\download-models.log in the data folder
)
pause
exit /b %RC%
