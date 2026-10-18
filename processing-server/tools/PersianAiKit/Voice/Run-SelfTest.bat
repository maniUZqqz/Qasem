@echo off
rem Persian voice - install self-test: text tools, text-to-speech, speech-to-text
chcp 65001 >nul
if exist "%~dp0app\PersianAiKit.Voice.SelfTest.exe" (
  cd /d "%~dp0app"
  "%~dp0app\PersianAiKit.Voice.SelfTest.exe" %*
) else (
  cd /d "%~dp0src\PersianAiKit.Voice.SelfTest"
  dotnet run -c Release -- %*
)
pause
