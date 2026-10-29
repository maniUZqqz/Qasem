@echo off
title UpMarket processing node
rem ================================================================
rem  UpMarket - processing node (GPU machine, no public IP needed)
rem  The ONLY file to run. Every start:
rem   1. the data folder (models, Python environments, this computer's identity) - outside this code folder,
rem      %USERPROFILE%\NMarketing-data unless chosen otherwise; the first time the downloads of OLDER copies
rem      of this folder are MOVED there (nothing is downloaded again, nothing is deleted);
rem   2. registration the first time: it asks for the enrollment key (panel > Tools > Processing servers >
rem      "Register a new server");
rem   3. a quiet update check: newer code from the site is applied here (Update.bat does the same by hand;
rem      set NM_AUTO_UPDATE=0 to turn it off);
rem   4. the node runs; it restarts by itself after an update, and a broken update is rolled back.
rem  The site URL comes from site.json (next to this file).
rem
rem  NOTE for whoever edits this file: the blocks in ( ) are read in one go and the labels :prepare and :loop
rem  must stay - an update may replace this file while it runs, and only that keeps the window working.
rem ================================================================
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python was not found. Install Python 3.10+ from python.org and tick "Add python to PATH".
  pause
  exit /b 1
)

rem ---- optional: start ComfyUI automatically (set NM_COMFY_BAT to run_nvidia_gpu.bat); normally the agent does it
if not "%NM_COMFY_BAT%"=="" if exist "%NM_COMFY_BAT%" start "ComfyUI" /min cmd /c "%NM_COMFY_BAT%"

:prepare
(
  python "%~dp0agent.py" --prepare
  if errorlevel 1 (
    echo [!] Registration failed - check the key / site URL above and run START.bat again.
    pause
    exit /b 1
  )
  if not "%NM_AUTO_UPDATE%"=="0" python "%~dp0update.py" --auto
  echo.
  echo Processing node is starting. Keep this window open. ^(Ctrl+C to stop^)
  echo.
  goto loop
)

:loop
(
  python "%~dp0agent.py"
  python "%~dp0update.py" --agent-exited
  echo.
  echo Agent stopped; restarting in 10 seconds ... ^(close this window to quit^)
  timeout /t 10 >nul
  goto loop
)
