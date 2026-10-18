@echo off
chcp 65001 >nul
title UpMarket 3D
rem ================================================================
rem  UpMarket 3D — اجرای کامل روی همین کامپیوتر (پنل + کارگردان + رندر با کارتِ گرافیک)
rem  بی‌نصب: پایتون، کتابخانه‌ها، Blender و FFmpeg داخلِ همین پوشه‌اند.
rem  پنل:  http://127.0.0.1:8030   (کاربر admin، رمز در data\admin-password.txt)
rem ================================================================
cd /d "%~dp0"
set "ROOT=%~dp0"
set "UP3D_ROOT=%~dp0"
set "UP3D_DATA=%~dp0data"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "PY=%~dp0vendor\python\python.exe"

if not exist "%PY%" (
  echo [!] vendor\python پیدا نشد. پوشه را کامل از زیپ بیرون بیاورید.
  pause & exit /b 1
)
if not exist "%~dp0vendor\blender\blender.exe" (
  if exist "%~dp0vendor\blender-windows.zip" (
    echo [1/3] باز کردنِ Blender 4.5 ^(فقط بارِ اول، چند دقیقه^) ...
    mkdir "%~dp0vendor\blender" 2>nul
    tar -xf "%~dp0vendor\blender-windows.zip" -C "%~dp0vendor\blender" --strip-components 1
    if exist "%~dp0vendor\blender\blender.exe" ( del "%~dp0vendor\blender-windows.zip" ) else ( echo [!] Blender باز نشد. & pause & exit /b 1 )
  )
)
echo [2/3] آماده‌سازیِ دیتابیس ...
"%PY%" "%~dp0web\manage.py" migrate --noinput >nul
"%PY%" "%~dp0web\manage.py" ensure_setup --local-worker local-gpu
set /p TOKEN=<"%~dp0data\local-worker.token"

echo [3/3] روشن کردنِ پنل، هماهنگ‌کننده و کارگرِ رندر ...
start "UP3D panel" /min "%PY%" -m waitress --listen=127.0.0.1:8030 --threads=8 config.wsgi:application
start "UP3D orchestrator" /min "%PY%" "%~dp0web\manage.py" orchestrator
timeout /t 4 >nul
start "UP3D worker (GPU)" "%PY%" -m up3d worker --server http://127.0.0.1:8030 --token %TOKEN% --name local-gpu --nice 0
timeout /t 3 >nul
start "" http://127.0.0.1:8030/
echo.
echo  پنل باز شد: http://127.0.0.1:8030
echo  کاربر: admin  ·  رمز: داخلِ data\admin-password.txt
echo  پنجرهٔ «UP3D worker» رندرها را نشان می‌دهد. برای خاموش کردن: stop.bat
echo.
pause
