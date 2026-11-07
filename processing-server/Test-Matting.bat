@echo off
title NMarketing - test photo matting
rem ================================================================
rem  Times every installed photo-matting model (u2netp, isnet, birefnet-lite) on a test picture, in the Python that has
rem  onnxruntime, and says whether the cut-out is plausible. Nothing is uploaded.
rem    Test-Matting.bat                 all installed models
rem    Test-Matting.bat --model isnet   one model
rem ================================================================
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
  echo [!] Python was not found. Install Python 3.10+ from python.org and tick "Add python to PATH".
  pause
  exit /b 1
)
%PY% "%~dp0photo_matting.py" test %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
