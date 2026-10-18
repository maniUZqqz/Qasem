@echo off
chcp 65001 >nul
title UpMarket 3D - GPU worker ({{NAME}})
rem ============================================================
rem  کارگرِ رندرِ UpMarket 3D روی ویندوز (کارتِ گرافیکِ NVIDIA/AMD)
rem  پیش‌نیاز: Python 3.10+  و  Blender 4.5 LTS (نصبِ معمولی)
rem  این فایل را در یک پوشهٔ خالی (مثلاً C:\up3d) بگذارید و اجرا کنید.
rem ============================================================
cd /d "%~dp0"
set "UP3D_ROOT=%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
rem اگر Blender جای دیگری نصب است، مسیرش را این‌جا بدهید:
rem set "UP3D_BLENDER=D:\Blender\blender.exe"

where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python پیدا نشد. از python.org نصب کنید و گزینهٔ Add to PATH را بزنید.
  pause & exit /b 1
)
if not exist "%~dp0up3d\__init__.py" (
  echo [1/2] دریافتِ بستهٔ کارگر از پنل ... (چند صد مگابایت؛ یک بار)
  curl.exe -f -L -H "Authorization: Worker {{TOKEN}}" -o "%~dp0bundle.zip" "{{SERVER}}/api/worker/bundle/"
  if errorlevel 1 ( echo [!] دریافت نشد. & pause & exit /b 1 )
  echo [2/2] باز کردن ...
  tar -xf "%~dp0bundle.zip" -C "%~dp0"
  del "%~dp0bundle.zip"
)
echo کارگر روشن شد. این پنجره را باز بگذارید. (برای توقف: Ctrl+C)
:loop
python -m up3d worker --server {{SERVER}} --token {{TOKEN}} --name {{NAME}} --nice 0
echo کارگر متوقف شد؛ ۱۰ ثانیهٔ دیگر دوباره روشن می‌شود ...
timeout /t 10 >nul
goto loop
