@echo off
rem UpMarket processing node - one-time setup of the photo / video / voice editors (PersianAiKit).
rem Downloads the ready Windows build of the three editors + ffmpeg + their models FROM THE SITE
rem (no .NET SDK, no VPN needed), then runs the diagnostic. Safe to run again.
rem ComfyUI (FLUX / Wan) and Ollama are installed separately; the agent finds ComfyUI's run_nvidia_gpu.bat by itself
rem (or put its path in services.json -> "comfyui" -> "start").
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ===== UpMarket processing node - editors setup =====
where python >nul 2>nul || (echo [!] Python not found. Install Python 3.11 x64 from python.org and tick "Add to PATH". & pause & exit /b 1)
python "%~dp0setup_kit.py"
echo.
echo ===== diagnostic =====
python "%~dp0agent.py" --check
echo.
echo Done. Start the node with START.bat; switch the editors on from the panel (Processing servers - services),
echo or leave auto-switch on and they start when a job needs them.
pause
