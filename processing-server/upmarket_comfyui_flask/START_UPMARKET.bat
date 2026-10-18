@echo off
setlocal EnableExtensions
title UpMarket - ComfyUI + Flask
cd /d "%~dp0"

set "COMFY_BAT=C:\Users\QQz\Desktop\N\ComfyUI_windows_portable\run_nvidia_gpu.bat"
set "COMFY_URL=http://127.0.0.1:8188"
set "PANEL_URL=http://127.0.0.1:5000"

for %%I in ("%COMFY_BAT%") do set "COMFY_DIR=%%~dpI"

echo ==========================================
echo        UpMarket Local AI Panel
echo ==========================================
echo.

if not exist "%COMFY_BAT%" (
  echo [ERROR] ComfyUI launcher not found:
  echo "%COMFY_BAT%"
  echo.
  echo Edit COMFY_BAT in START_UPMARKET.bat to match your ComfyUI location.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating Python virtual environment...
  py -3.10 -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Could not create venv. Check Python 3.10 installation.
    pause
    exit /b 1
  )
)

echo [2/4] Installing/checking Python requirements...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Dependency installation failed.
  pause
  exit /b 1
)

echo [3/4] Checking ComfyUI API...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing '%COMFY_URL%/system_stats' -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
  echo ComfyUI is not responding. Starting its launcher in a separate console...
  echo Launcher: "%COMFY_BAT%"
  start "UpMarket ComfyUI" /D "%COMFY_DIR%" "%ComSpec%" /k "call run_nvidia_gpu.bat"
  echo.
  echo Waiting up to 6 minutes for ComfyUI API. Check the separate ComfyUI window for errors.
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; for($i=0;$i -lt 180;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing '%COMFY_URL%/system_stats' -TimeoutSec 2; if($r.StatusCode -eq 200){$ok=$true; break} } catch {}; Start-Sleep -Seconds 2 }; if($ok){exit 0}else{exit 1}"
  if errorlevel 1 (
    echo.
    echo [ERROR] ComfyUI did not become available at %COMFY_URL%.
    echo The Flask panel will NOT be started because image/video generation cannot work.
    echo.
    echo In the separate ComfyUI window, find the first red error or traceback.
    echo Also verify that http://127.0.0.1:8188 opens in your browser.
    pause
    exit /b 2
  )
) else (
  echo ComfyUI API is already responding.
)

echo.
echo [4/4] Opening UpMarket panel...
start "" "%PANEL_URL%"
".venv\Scripts\python.exe" app.py

echo.
echo Flask panel stopped. Press any key to close this window.
pause >nul
