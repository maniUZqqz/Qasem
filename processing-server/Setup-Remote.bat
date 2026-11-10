@echo off
title NMarketing - remote access for the site (run once)
rem ================================================================
rem  Run ONCE on the processing node (double-click; Windows asks "Yes" for Administrator rights).
rem  Afterwards the site can stop / start / update this node from the panel and its administrator can work on it
rem  remotely - through a tunnel this computer opens to the site; nothing is opened to the internet or the network.
rem  START.bat must have run here once before (this computer has to be registered).
rem  Undo everything:  Setup-Remote.bat remove      Details: remote_setup.py
rem ================================================================
net session >nul 2>&1
if errorlevel 1 goto elevate
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python was not found. Install Python 3.10+ from python.org and tick "Add python to PATH".
  pause
  exit /b 1
)
python "%~dp0remote_setup.py" %*
echo.
pause
exit /b 0

:elevate
echo Asking Windows for Administrator rights ...
if "%~1"=="" (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
) else (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1' -Verb RunAs"
)
exit /b 0
