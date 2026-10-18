@echo off
title UpMarket 3D render worker
rem ============================================================
rem  3D render worker (Blender) - uses the same node token as agent.py
rem  Engine + assets ship in this folder (up3d\, engine\, assets\); nothing is downloaded
rem  except Blender itself, once, if it is not installed.
rem ============================================================
cd /d "%~dp0"
set "UP3D_ROOT=%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
if "%NM_SITE%"=="" (
  for /f "usebackq tokens=1,* delims==" %%a in (`python "%~dp0agent.py" --print-config`) do set "%%a=%%b"
)
if "%NM_SITE%"=="" ( echo [!] Site URL / token not set. Run START-^<node^>.bat first. & pause & exit /b 1 )

if not exist "%~dp0engine\run.py" ( echo [!] engine\run.py is missing - the package is incomplete. & pause & exit /b 1 )
if not exist "%~dp0up3d\__init__.py" ( echo [!] up3d\ folder is missing - the package is incomplete. & pause & exit /b 1 )

rem ---- find Blender: UP3D_BLENDER, vendor\blender\blender.exe, Program Files
set "BL="
if not "%UP3D_BLENDER%"=="" if exist "%UP3D_BLENDER%" set "BL=%UP3D_BLENDER%"
if "%BL%"=="" if exist "%~dp0vendor\blender\blender.exe" set "BL=%~dp0vendor\blender\blender.exe"
if "%BL%"=="" for /d %%d in ("%ProgramFiles%\Blender Foundation\*") do if exist "%%d\blender.exe" set "BL=%%d\blender.exe"
if "%BL%"=="" (
  echo Blender was not found. Downloading Blender 4.5 from the site once (about 400 MB) ...
  if not exist "%~dp0vendor" mkdir "%~dp0vendor"
  curl.exe -f -L -C - -o "%~dp0vendor\blender-windows.zip" "%NM_SITE%/3d/files/downloads/blender-windows.zip"
  if errorlevel 1 (
    echo [!] Download failed. Install Blender 4.5 LTS from blender.org, or set UP3D_BLENDER to blender.exe, then run again.
    pause & exit /b 1
  )
  echo Extracting ...
  mkdir "%~dp0vendor\blender" 2>nul
  tar -xf "%~dp0vendor\blender-windows.zip" -C "%~dp0vendor\blender" --strip-components 1
  if exist "%~dp0vendor\blender\blender.exe" (
    del "%~dp0vendor\blender-windows.zip"
    set "BL=%~dp0vendor\blender\blender.exe"
  ) else (
    echo [!] Extraction failed - the zip stays at vendor\blender-windows.zip; unzip it so that vendor\blender\blender.exe exists.
    pause & exit /b 1
  )
)
set "UP3D_BLENDER=%BL%"
echo Blender: %BL%
echo 3D worker '%NM_NODE%' starting (server %NM_SITE%/3d).
:loop
python -m up3d worker --server %NM_SITE%/3d --token %NM_TOKEN% --name %NM_NODE% --nice 0
echo Worker stopped; restarting in 10 seconds ...
timeout /t 10 >nul
goto loop
