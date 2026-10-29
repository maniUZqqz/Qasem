@echo off
title UpMarket 3D render worker
rem ============================================================
rem  3D render worker (Blender) - uses the same node token as agent.py
rem  Engine + assets ship in this folder (up3d\, engine\, assets\). Downloaded once from the site:
rem    Blender 4.5            -> <data folder>\vendor\blender\        (blender-windows.zip, ~400 MB)
rem    MPFB human data        -> <data folder>\vendor\blender-user\   (up3d-blender-user.zip; for the presenters)
rem  The data folder (NM_DATA, %USERPROFILE%\NMarketing-data unless chosen otherwise) survives code updates.
rem  Downloads resume after a dropped connection and are checked before they are unpacked.
rem  Normally started by agent.py (panel: Processing servers > services > "3D render"); can also be run by hand.
rem ============================================================
cd /d "%~dp0"
set "UP3D_ROOT=%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
if "%NM_SITE%"=="" (
  for /f "usebackq tokens=1,* delims==" %%a in (`python "%~dp0agent.py" --print-config`) do set "%%a=%%b"
)
if "%NM_SITE%"=="" ( echo [!] Site URL / token not set. Run START.bat first. & timeout /t 30 >nul & exit /b 1 )
if "%NM_DATA%"=="" for /f "usebackq delims=" %%a in (`python "%~dp0nm_data.py" --print`) do set "NM_DATA=%%a"
if "%NM_DATA%"=="" set "NM_DATA=%~dp0."
set "VENDOR=%NM_DATA%\vendor"
if "%UP3D_DATA%"=="" set "UP3D_DATA=%NM_DATA%\data"

if not exist "%~dp0engine\run.py" ( echo [!] engine\run.py is missing - the package is incomplete. & timeout /t 30 >nul & exit /b 1 )
if not exist "%~dp0up3d\__init__.py" ( echo [!] up3d\ folder is missing - the package is incomplete. & timeout /t 30 >nul & exit /b 1 )
if not exist "%VENDOR%" mkdir "%VENDOR%"

rem ---- find Blender: UP3D_BLENDER, <data folder>\vendor\blender\blender.exe, Program Files
set "BL="
if not "%UP3D_BLENDER%"=="" if exist "%UP3D_BLENDER%" set "BL=%UP3D_BLENDER%"
if "%BL%"=="" if exist "%VENDOR%\blender\blender.exe" set "BL=%VENDOR%\blender\blender.exe"
if "%BL%"=="" for /d %%d in ("%ProgramFiles%\Blender Foundation\*") do if exist "%%d\blender.exe" set "BL=%%d\blender.exe"
if "%BL%"=="" (
  echo Blender was not found. Downloading Blender 4.5 from the site once ^(about 400 MB^) ...
  call :fetch blender-windows.zip "%VENDOR%\blender" 1
  if exist "%VENDOR%\blender\blender.exe" set "BL=%VENDOR%\blender\blender.exe"
)
if "%BL%"=="" (
  echo [!] Blender is still missing. Install Blender 4.5 LTS from blender.org, or set UP3D_BLENDER to blender.exe.
  timeout /t 60 >nul & exit /b 1
)

rem ---- MPFB (MakeHuman) add-on + skins/clothes/hair for the human presenters
if "%UP3D_BLENDER_USER%"=="" set "UP3D_BLENDER_USER=%VENDOR%\blender-user"
if not exist "%UP3D_BLENDER_USER%\extensions\user_default\mpfb\__init__.py" (
  echo The human-character data ^(MPFB^) is missing. Downloading it once ^(about 430 MB^) ...
  call :fetch up3d-blender-user.zip "%VENDOR%" 0
)
if not exist "%UP3D_BLENDER_USER%\extensions\user_default\mpfb\__init__.py" (
  echo [!] MPFB data missing: scenes with the built-in presenters will fail on this machine until it is downloaded.
)

set "UP3D_BLENDER=%BL%"
echo Blender: %BL%
echo Characters: %UP3D_BLENDER_USER%
echo 3D worker '%NM_NODE%' starting (server %NM_SITE%/3d).
rem the loop is one block (read in one go) so an update that replaces this file while it runs does no harm
:loop
(
  python -m up3d worker --server %NM_SITE%/3d --token %NM_TOKEN% --name %NM_NODE% --nice 0
  echo Worker stopped; restarting in 10 seconds ...
  timeout /t 10 >nul
  goto loop
)

rem ---- :fetch <file on the site> <folder to unpack into> <strip first folder 1|0>
:fetch
set "ZIP=%VENDOR%\%~1"
set /a TRY=0
:fetch_again
set /a TRY+=1
if exist "%ZIP%" (
  tar -tf "%ZIP%" >nul 2>nul
  if not errorlevel 1 goto fetch_unpack
)
echo Downloading %~1 ^(attempt %TRY%^) ...
curl.exe -f -L -C - --retry 5 --retry-delay 10 --connect-timeout 30 -o "%ZIP%" "%NM_SITE%/3d/files/downloads/%~1"
tar -tf "%ZIP%" >nul 2>nul
if not errorlevel 1 goto fetch_unpack
if %TRY% GEQ 8 (
  echo [!] Could not download %~1 after %TRY% attempts. The partial file stays in %VENDOR% and the next start continues it.
  exit /b 1
)
echo Download incomplete; continuing in 15 seconds ...
timeout /t 15 >nul
goto fetch_again
:fetch_unpack
echo Extracting %~1 ...
if not exist "%~2" mkdir "%~2"
if "%~3"=="1" (
  tar -xf "%ZIP%" -C "%~2" --strip-components 1
) else (
  tar -xf "%ZIP%" -C "%~2"
)
if errorlevel 1 ( echo [!] Extraction of %~1 failed. & exit /b 1 )
del "%ZIP%"
exit /b 0
