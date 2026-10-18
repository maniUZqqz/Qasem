@echo off
rem Photo editor - install self-test (light: under 1 GB RAM, about 15 seconds)
rem Your own photos:  Run-SelfTest.bat --photos D:\pics      Heavy models (server only):  Run-SelfTest.bat --heavy
rem Rebuild FEATURES.md:  Run-SelfTest.bat --write-docs
chcp 65001 >nul
if exist "%~dp0app\PersianAiKit.Photo.SelfTest.exe" (
  cd /d "%~dp0app"
  "%~dp0app\PersianAiKit.Photo.SelfTest.exe" %*
) else (
  cd /d "%~dp0src\PersianAiKit.Photo.SelfTest"
  dotnet run -c Release -- %*
)
pause
