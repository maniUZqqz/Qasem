@echo off
title UpMarket - download models
rem ================================================================
rem  UpMarket processing node - download every model the node can run.
rem  Reads downloads\*.json (voice.json, video.json, ...). Safe to run again:
rem  finished files are skipped, broken downloads continue where they stopped.
rem
rem    Download-Models.bat                 everything (asks once before starting)
rem    Download-Models.bat --list          what is still missing, with sizes
rem    Download-Models.bat --check         test every link without downloading
rem    Download-Models.bat --only voice    only one group / package
rem    Download-Models.bat --skip acestep  leave a package out
rem    Download-Models.bat --hf-mirror https://hf-mirror.com
rem  Log: logs\download-models.log
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
%PY% "%~dp0download_models.py" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo Finished. Restart START.bat so the site sees the new models.
) else (
  echo Finished with problems - read the summary above, or logs\download-models.log
)
pause
exit /b %RC%
