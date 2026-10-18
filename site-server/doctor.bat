@echo off
chcp 65001 >nul
setlocal
title UpMarket — Doctor

REM ============================================================
REM  "هیچی کار نمی‌کند" شش معنی مختلف دارد و از بیرون همه شبیه هم‌اند:
REM  Redis خاموش، کارگر صف خاموش، آدرس Ollama فرق دارد، ComfyUI نصب
REM  نیست، سایت وقتی بیلد شده که بک‌اند بالا نبوده، یا پنل به آدرس
REM  اشتباه وصل است. این فایل هر شش را یک‌جا می‌سنجد و جواب را در
REM  logs\doctor.txt می‌نویسد.
REM
REM  چیزی را روشن یا خاموش نمی‌کند. برای بالا آوردن پروژه: start.bat
REM ============================================================

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"

where python >nul 2>nul
if errorlevel 1 (
    echo [BAD ] Python روی این سیستم پیدا نشد — بدون آن هیچ‌چیز اجرا نمی‌شود.
    echo         از python.org نصبش کنید و دوباره همین فایل را اجرا کنید.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo    بررسی سلامت آپ‌مارکت
echo  ============================================
echo.

pushd "%BACKEND%"
set PYTHONIOENCODING=utf-8
python manage.py doctor
popd

echo.
echo  گزارش در logs\doctor.txt ذخیره شد.
echo.
pause
