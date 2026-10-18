@echo off
rem Persian voice (PersianAiKit.Voice) - HTTP server + test page (http://localhost:5600)
rem Starts the Python voice service by itself when installed (Setup-Voice.bat).
rem Settings: appppsettings.json (or src\PersianAiKit.Voice.Serverppsettings.json when running from source)
chcp 65001 >nul
if exist "%~dp0app\PersianAiKit.Voice.Server.exe" (
  cd /d "%~dp0app"
  "%~dp0app\PersianAiKit.Voice.Server.exe" %*
) else (
  cd /d "%~dp0src\PersianAiKit.Voice.Server"
  dotnet run -c Release -- %*
)
pause
