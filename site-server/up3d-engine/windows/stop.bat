@echo off
chcp 65001 >nul
rem خاموش کردنِ پنل، هماهنگ‌کننده و کارگر (و Blender ِ در حالِ رندر)
taskkill /FI "WINDOWTITLE eq UP3D*" /T /F >nul 2>nul
echo UpMarket 3D خاموش شد.
timeout /t 2 >nul
