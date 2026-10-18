@echo off
rem Photo editor (PersianAiKit.Photo) - web editor + HTTP API for other programs and AI (http://localhost:5670)
rem Settings: app\appsettings.json (or src\PersianAiKit.Photo.Server\appsettings.json when running from source)
rem The browser opens by itself when the server is ready.
chcp 65001 >nul
if exist "%~dp0app\PersianAiKit.Photo.Server.exe" (
  cd /d "%~dp0app"
  "%~dp0app\PersianAiKit.Photo.Server.exe" --Photo:OpenBrowser=true %*
) else (
  cd /d "%~dp0src\PersianAiKit.Photo.Server"
  dotnet run -c Release -- --Photo:OpenBrowser=true %*
)
pause
