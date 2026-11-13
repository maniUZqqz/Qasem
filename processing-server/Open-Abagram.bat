@echo off
title NMarketing - open Abagram on this computer
rem ================================================================
rem  Opens Abagram (the Instagram reader of this processing node) in your browser, already past its door.
rem  Use it once to sign in to Instagram (and again only if Instagram throws the login out):
rem    1. start START.bat and keep it open - the first start installs Abagram by itself (a few minutes);
rem    2. run this file; sign in on the first page (Instagram's own checks/captcha are done in that page too);
rem    3. Instagram is filtered in Iran: if your VPN is a program on this computer (v2rayN ...), put its local address in
rem       Settings > Proxy of Abagram (for v2rayN: http://127.0.0.1:10809). The node tries your Windows system proxy by itself.
rem  The door is a key only this computer knows; nothing is opened to the network.
rem ================================================================
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
  echo [!] Python was not found. Install Python 3.10+ from python.org and tick "Add python to PATH".
  pause
  exit /b 1
)
%PY% "%~dp0abagram_jobs.py" open-ui
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
