@echo off
chcp 65001 >nul
title UpMarket - Redis installer

REM ============================================================
REM  Kept only so an old shortcut or an old note still works.
REM
REM  start.bat now offers to install Redis itself, along with ffmpeg and
REM  everything else, so there is nothing here that it does not do better —
REM  it knows whether Redis is already present, and it carries on afterwards
REM  instead of leaving you at a second prompt.
REM ============================================================

echo.
echo  This installer has moved into start.bat.
echo.
echo  Run start.bat — it checks for Redis and offers to install it,
echo  then starts everything. Or, to install without launching:
echo.
echo      start.bat /install
echo.

choice /c YN /n /m "Run start.bat /install now? [Y/N] "
if errorlevel 2 exit /b 0
call "%~dp0start.bat" /install
