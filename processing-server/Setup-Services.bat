@echo off
rem UpMarket processing node - one-time setup of the optional services:
rem   photo / video / voice editors (PersianAiKit, .NET 8), their models, ffmpeg, and the diagnostic.
rem Safe to run again: every step skips what is already done. Needs internet (or the site) for the first run.
rem ComfyUI (FLUX / Wan) and Ollama are installed separately; the agent finds ComfyUI's run_nvidia_gpu.bat by itself
rem (or put its path in services.json -> "comfyui" -> "start").
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ===== UpMarket processing node - services setup =====
echo.

rem ---- 1) .NET SDK 8+ (needed to build/publish the editors once)
set "DOTNET_OK="
for /f "tokens=1" %%v in ('dotnet --list-sdks 2^>nul') do (
  for /f "delims=. tokens=1" %%m in ("%%v") do if %%m GEQ 8 set "DOTNET_OK=1"
)
if defined DOTNET_OK (
  echo [1/6] .NET SDK: OK
) else (
  echo [1/6] .NET SDK 8 not found - installing with winget ^(Windows 10/11^) ...
  winget install --id Microsoft.DotNet.SDK.8 -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo [!] winget could not install it. Install ".NET 8 SDK" from https://dotnet.microsoft.com/download/dotnet/8.0 and run this file again.
    pause
    exit /b 1
  )
  set "PATH=%ProgramFiles%\dotnet;%PATH%"
)

rem ---- 2) publish the three editors into app\ (then Run-Server.bat starts the exe in seconds instead of building)
for %%K in (Photo Video Voice) do call :publish %%K

rem ---- 3) ffmpeg for the video editor (winget Gyan.FFmpeg, or BtbN zip into tools\ffmpeg\bin)
echo [3/6] ffmpeg for the video editor
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\PersianAiKit\Video\tools\Install-FFmpeg.ps1"
if errorlevel 1 echo [!] ffmpeg install failed - the video editor cannot run without it (see tools\PersianAiKit\Video\README.md)

rem ---- 4) models: Piper voices + Vosk (voice), upscaler (photo) - from the site first, internet as fallback
echo [4/6] models for the voice and photo editors
python "%~dp0setup_models.py"

rem ---- 5) voice editor data folder (first start creates the rest)
echo [5/6] voice editor: natural voices / voice cloning are optional (3.4 GB): tools\PersianAiKit\Voice\Setup-Voice.bat

rem ---- 6) diagnostic
echo [6/6] diagnostic
python "%~dp0agent.py" --check
echo.
echo Setup finished. Start the node with START.bat; switch the editors on from the panel (Processing servers - services).
pause
exit /b 0

:publish
set "K=%~1"
if exist "tools\PersianAiKit\%K%\app\PersianAiKit.%K%.Server.exe" (
  echo [2/6] %K% editor: already published ^(tools\PersianAiKit\%K%\app^)
  goto :eof
)
echo [2/6] publishing the %K% editor ^(first time: a few minutes, downloads NuGet packages^) ...
dotnet publish "tools\PersianAiKit\%K%\src\PersianAiKit.%K%.Server\PersianAiKit.%K%.Server.csproj" -c Release -o "tools\PersianAiKit\%K%\app" --nologo -v q
if errorlevel 1 (
  echo [!] %K% publish failed - see the messages above. Run-Server.bat will fall back to "dotnet run" ^(slow first start^).
) else (
  echo       %K% editor: OK
)
goto :eof
