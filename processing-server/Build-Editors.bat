@echo off
rem ============================================================================================
rem  Build the photo / video / voice editors (PersianAiKit) with the .NET SDK on THIS machine.
rem
rem  How the libraries get here: "dotnet restore" downloads every NuGet package the editors list in
rem  their .csproj files (OpenCvSharp, ONNX Runtime, Vosk, NAudio, ...) from https://api.nuget.org
rem  into %USERPROFILE%\.nuget\packages (once; later builds reuse them). "dotnet publish" then puts
rem  the finished editor in <data folder>\tools\PersianAiKit\<Editor>\app\ - Run-Server.bat starts that exe.
rem  (Agent 2.0: the editors live in the data folder, %USERPROFILE%\NMarketing-data unless chosen otherwise,
rem  so a new copy of the code never builds them again.)
rem
rem  The agent does the same thing by itself the first time a job needs an editor, so this file is
rem  only for doing it ahead of time and SEEING every step. If nuget.org is blocked on this line,
rem  use Setup-Services.bat instead (it downloads the ready-built editors from the site).
rem  Safe to run again: an editor that is already built is rebuilt only with  Build-Editors.bat force
rem ============================================================================================
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
rem ---- the data folder (the editors' source is copied there by nm_data.py; builds stay there)
set "NM_DATA="
for /f "usebackq delims=" %%a in (`python "%~dp0nm_data.py" --print`) do set "NM_DATA=%%a"
if not defined NM_DATA set "NM_DATA=%~dp0."
python "%~dp0nm_data.py" >nul
cd /d "%NM_DATA%"
echo Editors are built in: %NM_DATA%\tools\PersianAiKit

rem ---- find a .NET SDK 8+ (also when it is not on PATH)
set "DOTNET="
for %%D in (dotnet.exe) do if not "%%~$PATH:D"=="" set "DOTNET=%%~$PATH:D"
if not defined DOTNET if exist "%ProgramFiles%\dotnet\dotnet.exe" set "DOTNET=%ProgramFiles%\dotnet\dotnet.exe"
if not defined DOTNET if exist "%LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe" set "DOTNET=%LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe"
if not defined DOTNET (
  echo [!] .NET SDK not found. Install ".NET 8 SDK" ^(https://dotnet.microsoft.com/download/dotnet/8.0^) or run Setup-Services.bat.
  exit /b 1
)
echo .NET: "%DOTNET%"
"%DOTNET%" --list-sdks
echo.
echo NuGet source check ...
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 https://api.nuget.org/v3/index.json).StatusCode } catch { 'unreachable: ' + $_.Exception.Message }"
echo.

set FAILED=
for %%K in (Photo Video Voice) do (
  set "APP=tools\PersianAiKit\%%K\app\PersianAiKit.%%K.Server.exe"
  set "PROJ=tools\PersianAiKit\%%K\src\PersianAiKit.%%K.Server\PersianAiKit.%%K.Server.csproj"
  set "DO=1"
  if exist "!APP!" set "DO=0"
  if /i "%~1"=="force" set "DO=1"
  if "!DO!"=="0" (
    echo [%%K] already built - skip ^(use: Build-Editors.bat force^)
  ) else (
    echo ===== [%%K] 1/2 restore: downloading NuGet packages ^(first time can take several minutes^) =====
    "%DOTNET%" restore "!PROJ!" -v minimal
    if errorlevel 1 (
      echo [%%K] restore FAILED - nuget.org not reachable? Try again, use a VPN, or run Setup-Services.bat
      set FAILED=1
    ) else (
      echo ===== [%%K] 2/2 publish into tools\PersianAiKit\%%K\app =====
      "%DOTNET%" publish "!PROJ!" -c Release -o "tools\PersianAiKit\%%K\app" --no-restore --nologo -v minimal
      if errorlevel 1 ( echo [%%K] publish FAILED & set FAILED=1 ) else ( echo [%%K] OK )
    )
  )
  echo.
)
if exist logs\nul echo Logs of the agent's own builds: logs\build-*.log
if defined FAILED (
  echo Some editors were not built - see the lines above.
) else (
  echo All editors are built. Restart START.bat if it is running.
)
if /i not "%~2"=="nopause" pause
