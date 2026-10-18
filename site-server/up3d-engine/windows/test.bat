@echo off
chcp 65001 >nul
title UpMarket 3D - test
rem آزمونِ این کامپیوتر: هستهٔ برنامه + تشخیصِ کارتِ گرافیک + یک ویدئوی کوتاهِ واقعی از سر تا ته
cd /d "%~dp0"
set "UP3D_ROOT=%~dp0"
set "UP3D_DATA=%~dp0data"
set "PYTHONIOENCODING=utf-8"
set "PY=%~dp0vendor\python\python.exe"
if not exist "%~dp0vendor\blender\blender.exe" ( echo اول یک بار start.bat را اجرا کنید تا Blender باز شود. & pause & exit /b 1 )

echo ===== ۱) آزمون‌های هسته =====
"%PY%" -m unittest discover -s tests -p "test_*.py"
echo.
echo ===== ۲) کارتِ گرافیک (از نگاهِ Blender) =====
"%PY%" -c "from up3d.worker import probe_devices; d = probe_devices(); print('Blender', d.get('blender_version'), '| GPU:', d.get('gpu') or 'پیدا نشد (با CPU کار می‌کند)')"
echo.
echo ===== ۳) یک ویدئوی کوتاه (انیمیک) از سر تا ته =====
"%PY%" -m up3d template showcase --brief tests\brief_sample.json -o "%TEMP%\up3d_scene.json"
"%PY%" -m up3d render "%TEMP%\up3d_scene.json" --profile animatic --job-dir "%~dp0data\jobs\test-local"
echo.
echo اگر «کیفیت: pass» یا «warn» دیدید، همه‌چیز درست است. ویدئو: data\jobs\test-local\final.mp4
pause
