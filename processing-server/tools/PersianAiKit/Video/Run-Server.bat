@echo off
rem Video editor (PersianAiKit.Video) - web editor + HTTP API for other programs and AI (http://localhost:5680)
rem Needs FFmpeg: tools\Install-FFmpeg.ps1   Settings: src\PersianAiKit.Video.Server\appsettings.json (or app\appsettings.json)
rem The browser opens by itself when the server is ready.
chcp 65001 >nul
if exist "%~dp0app\PersianAiKit.Video.Server.exe" (
  cd /d "%~dp0app"
  "%~dp0app\PersianAiKit.Video.Server.exe" --Video:OpenBrowser=true %*
) else (
  cd /d "%~dp0src\PersianAiKit.Video.Server"
  dotnet run -c Release -- --Video:OpenBrowser=true %*
)
pause
