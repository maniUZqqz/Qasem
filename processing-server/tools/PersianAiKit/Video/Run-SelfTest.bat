@echo off
rem Video editor - install self-test (light: tiny synthetic clips, about 30 seconds, under 200 MB RAM)
rem Your own video:  Run-SelfTest.bat --video D:\clip.mp4      Rebuild FEATURES.md:  Run-SelfTest.bat --write-docs
chcp 65001 >nul
if exist "%~dp0app\PersianAiKit.Video.SelfTest.exe" (
  cd /d "%~dp0app"
  "%~dp0app\PersianAiKit.Video.SelfTest.exe" %*
) else (
  cd /d "%~dp0src\PersianAiKit.Video.SelfTest"
  dotnet run -c Release -- %*
)
pause
