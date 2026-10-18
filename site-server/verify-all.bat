@echo off
chcp 65001 >nul
setlocal EnableExtensions

title UpMarket - verify everything

REM ============================================================
REM  UpMarket - run every check there is, write ONE report.
REM
REM  Double-click it and walk away. It starts what it needs (Redis, Ollama,
REM  ComfyUI), runs everything with a time limit on every step, stops what
REM  it started, and leaves in  logs\verify\ :
REM
REM      SUMMARY.txt    one PASS/FAIL line per step, with how long it took
REM      ERRORS.txt     for every failure: what broke, the lines of the log
REM                     that say why, and what to do about it
REM      artifacts\     the image and the clip the real models made
REM
REM  Made for the MAIN system - the one with the GPU - because half of what
REM  matters can only be checked there. That folder is tracked by git on
REM  purpose: run push.bat afterwards and the report travels back.
REM
REM  Usage:
REM     verify-all.bat              everything            (1 to 2 hours)
REM     verify-all.bat /quick       skip the long test suite and the builds
REM     verify-all.bat /fastai      real stack: only "is it there", no generation
REM     verify-all.bat /fullvideo   render a production-length clip (81 frames)
REM     verify-all.bat /noreal      no GPU here - skip the real-stack step
REM
REM  If ComfyUI is not found automatically, either start it yourself first,
REM  or say where it lives before running:
REM     set COMFYUI_DIR=D:\AI\ComfyUI_windows_portable
REM
REM  This file is only a launcher, on purpose. Everything it used to do in
REM  batch now lives in backend\tools\verify_all.py, because batch can neither
REM  put a time limit on a step nor survive a folder name with brackets in it
REM  without care - and the first version of this proved both.
REM ============================================================

set "ROOT=%~dp0"
set "ARGS="

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="/quick"     set "ARGS=%ARGS% --quick"
if /i "%~1"=="/fastai"    set "ARGS=%ARGS% --fastai"
if /i "%~1"=="/fullvideo" set "ARGS=%ARGS% --fullvideo"
if /i "%~1"=="/noreal"    set "ARGS=%ARGS% --noreal"
shift
goto parse_args
:args_done

where python >nul 2>nul
if errorlevel 1 goto no_python

pushd "%ROOT%backend"
python tools\verify_all.py %ARGS%
set "RC=%errorlevel%"
popd

echo.
pause
exit /b %RC%

:no_python
echo.
echo [STOP] Python is not installed, or not on your PATH.
echo.
echo        1. Download Python 3.10 or newer from python.org
echo        2. During install, TICK "Add python.exe to PATH"
echo        3. Close this window, open a new one, run verify-all.bat again
echo.
pause
exit /b 1
