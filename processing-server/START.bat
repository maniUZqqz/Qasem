@echo off
title UpMarket processing node
rem ================================================================
rem  UpMarket - processing node (GPU machine, no public IP needed)
rem  ONE file for every machine. First run: it asks for the enrollment key
rem  (panel > Tools > Processing servers > "Register a new server"), registers this
rem  computer under its own name and saves node.json. Next runs: just start.
rem  The site URL comes from site.json (next to this file).
rem ================================================================
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python was not found. Install Python 3.10+ from python.org and tick "Add python to PATH".
  pause & exit /b 1
)

if not exist "%~dp0node.json" (
  echo This computer is not registered yet.
  if "%NM_ENROLL_KEY%"=="" set /p NM_ENROLL_KEY=Enrollment key from the panel:
  if "%NM_NODE%"=="" set "NM_NODE=%COMPUTERNAME%"
  python "%~dp0agent.py" --check
  if not exist "%~dp0node.json" (
    echo [!] Registration failed - check the key / site URL above and run again.
    pause & exit /b 1
  )
) else (
  echo.
  echo ===== Diagnostic =====
  python "%~dp0agent.py" --check
  echo ======================
)

rem ---- optional: start ComfyUI automatically (set NM_COMFY_BAT to run_nvidia_gpu.bat)
if not "%NM_COMFY_BAT%"=="" if exist "%NM_COMFY_BAT%" (
  echo Starting ComfyUI: %NM_COMFY_BAT%
  start "ComfyUI" /min cmd /c "%NM_COMFY_BAT%"
)

rem ---- 3D render worker (Blender) in its own window when the up3d folder is present
if exist "%~dp0up3d\__init__.py" (
  start "UpMarket 3D worker" /min cmd /c "%~dp0worker-3d.bat"
)

echo.
echo Processing node is running. Keep this window open. (Ctrl+C to stop)
echo.
:loop
python "%~dp0agent.py"
echo.
echo Agent stopped; restarting in 10 seconds ... (close this window to quit)
timeout /t 10 >nul
goto loop
