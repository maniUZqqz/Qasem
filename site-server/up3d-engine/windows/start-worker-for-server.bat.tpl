@echo off
chcp 65001 >nul
title UP3D worker for server ({{NAME}})
rem ================================================================
rem  حالتِ دوم: این کامپیوتر فقط «کارگرِ GPU» ِ پنلِ روی سرور می‌شود
rem  (پروژه‌ها در {{SERVER}} می‌مانند؛ رندرهای باکیفیت این‌جا انجام می‌شوند)
rem ================================================================
cd /d "%~dp0"
set "UP3D_ROOT=%~dp0"
set "UP3D_DATA=%~dp0data"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "PY=%~dp0vendor\python\python.exe"
if not exist "%~dp0vendor\blender\blender.exe" ( echo اول یک بار start.bat را اجرا کنید تا Blender باز شود. & pause & exit /b 1 )
:loop
"%PY%" -m up3d worker --server {{SERVER}} --token {{TOKEN}} --name {{NAME}} --nice 0
echo کارگر متوقف شد؛ ۱۰ ثانیهٔ دیگر دوباره ...
timeout /t 10 >nul
goto loop
