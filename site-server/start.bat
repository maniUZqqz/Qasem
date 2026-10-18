@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

title UpMarket Launcher

REM ============================================================
REM  UpMarket — one launcher for everything.
REM
REM  It does four things, in this order:
REM    1. Checks what is installed, and OFFERS TO INSTALL what is not.
REM    2. Asks, once, which AI work runs here and which goes to an API —
REM       separately for text, image and video.
REM    3. Starts only the engines that are actually needed.
REM    4. Health-checks what it started, and says what to do about anything
REM       that did not come up.
REM
REM  Two rules it follows throughout:
REM
REM  * A MISSING OPTIONAL THING IS A WARNING, NEVER A STOP. A machine without
REM    ffmpeg should still get a working dashboard and a clear sentence about
REM    what will not work. Refusing to start would be the launcher deciding
REM    the whole product is useless because one part of it is.
REM
REM  * A MISSING ESSENTIAL THING STOPS, AND SAYS EXACTLY WHAT TO DO. Python
REM    and Node cannot be worked around, so there is no point starting.
REM
REM  Usage:
REM    start.bat            normal run
REM    start.bat /notest    skip the self-check (faster)
REM    start.bat /setup     re-ask the local-or-API questions
REM    start.bat /install   only install missing things, then exit
REM    start.bat /minimal   dashboard + backend only, no website, no AI engines
REM    start.bat /sitedev   serve the public website from its dev server, so
REM                         edits to it reload live. Every page is seconds
REM                         slower on first visit — see :website_build.
REM ============================================================

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "WEBSITE=%ROOT%website"
set "LOGDIR=%ROOT%logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" 2>nul

REM ComfyUI: leave EMPTY to auto-detect. Set it only to override the search.
set "COMFYUI_DIR="
set "COMFYUI_CMD=run_nvidia_gpu.bat"

set "START_OLLAMA=1"
set "START_WEBSITE=1"
set "WEBSITE_DEV=0"
set "SKIP_SELFTEST=0"
set "INSTALL_ONLY=0"
set "FORCE_SETUP=0"

REM ---- flags ------------------------------------------------------------
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="/notest"  set "SKIP_SELFTEST=1"
if /i "%~1"=="/setup"   set "FORCE_SETUP=1"
if /i "%~1"=="/install" set "INSTALL_ONLY=1"
if /i "%~1"=="/sitedev" set "WEBSITE_DEV=1"
if /i "%~1"=="/minimal" (
    set "START_WEBSITE=0"
    set "START_OLLAMA=0"
    set "SKIP_SELFTEST=1"
)
if /i "%~1"=="/?"    goto show_help
if /i "%~1"=="--help" goto show_help
shift
goto parse_args
:args_done

echo.
echo  ============================================
echo    UpMarket — checking what you have
echo  ============================================
echo.

REM ============================================================
REM  1. THINGS WITHOUT WHICH NOTHING RUNS
REM ============================================================

where python >nul 2>nul
if errorlevel 1 goto fail_python
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo [OK]   %PYVER%

where npm >nul 2>nul
if errorlevel 1 goto fail_node
echo [OK]   Node.js / npm

REM ============================================================
REM  2. THINGS WE CAN INSTALL FOR YOU
REM
REM  Each one asks first. Downloading several hundred megabytes onto
REM  somebody's machine without asking is not a favour.
REM ============================================================

REM ---- ffmpeg: video, audio, subtitles, editing. Nothing media works
REM      without it, and everything LOOKS fine until the first render.
set "HAS_FFMPEG=0"
where ffmpeg >nul 2>nul && set "HAS_FFMPEG=1"
if "%HAS_FFMPEG%"=="0" if exist "%ROOT%ffmpeg\bin\ffmpeg.exe" (
    set "PATH=%ROOT%ffmpeg\bin;%PATH%"
    set "HAS_FFMPEG=1"
)
if "%HAS_FFMPEG%"=="1" goto ffmpeg_ok
echo [MISSING] ffmpeg — no video, no voice, no subtitles, no editing.
call :ask "Download ffmpeg now? About 190 MB, and it takes a while."
if /i not "%ANSWER%"=="y" goto ffmpeg_done
call :install_ffmpeg
goto ffmpeg_done
:ffmpeg_ok
echo [OK]   ffmpeg
:ffmpeg_done

REM ---- Redis: the queue. Without it video generation cannot run, because a
REM      render that takes minutes cannot live inside a web request.
set "HAS_REDIS=0"
set "REDIS_CMD=redis-server"
if exist "%ROOT%redis\redis-server.exe" (
    set "HAS_REDIS=1"
    set "REDIS_CMD=%ROOT%redis\redis-server.exe"
)
if "%HAS_REDIS%"=="0" where redis-server >nul 2>nul && set "HAS_REDIS=1"
if "%HAS_REDIS%"=="1" goto redis_ok
echo [MISSING] Redis — video generation will be OFF. Everything else works.
call :ask "Download a portable Redis into this folder? About 6 MB."
if /i not "%ANSWER%"=="y" goto redis_done
call :install_redis
goto redis_done
:redis_ok
echo [OK]   Redis
:redis_done

REM ---- Ollama: text and vision. Only needed if you chose "local" for those,
REM      which we have not asked yet — so this is informational for now.
set "HAS_OLLAMA=0"
where ollama >nul 2>nul && set "HAS_OLLAMA=1"
if "%HAS_OLLAMA%"=="1" (
    echo [OK]   Ollama
) else (
    echo [INFO] Ollama not found — fine if you use an API for text.
)

REM ============================================================
REM  3. PROJECT SETUP
REM ============================================================

if not exist "%BACKEND%\.env" (
    if exist "%BACKEND%\.env.example" (
        copy "%BACKEND%\.env.example" "%BACKEND%\.env" >nul
        echo [setup] backend\.env created from .env.example
    )
)

if "%HAS_FFMPEG%"=="1" if exist "%ROOT%ffmpeg\bin\ffmpeg.exe" call :pin_ffmpeg_path

echo [..]   Checking Python packages ...
set "NEED_PIP=0"
python -c "import django"         >nul 2>nul || set "NEED_PIP=1"
python -c "import rest_framework" >nul 2>nul || set "NEED_PIP=1"
python -c "import celery"         >nul 2>nul || set "NEED_PIP=1"
python -c "import dotenv"         >nul 2>nul || set "NEED_PIP=1"
python -c "import PIL"            >nul 2>nul || set "NEED_PIP=1"
python -c "import requests"       >nul 2>nul || set "NEED_PIP=1"

if "%NEED_PIP%"=="1" (
    echo [setup] Installing backend packages — first run only, please wait...
    pushd "%BACKEND%"
    python -m pip install --upgrade pip >nul 2>nul
    pip install -r requirements.txt
    if errorlevel 1 (
        popd
        goto fail_pip
    )
    popd
)

python -c "import django,rest_framework,celery" >nul 2>nul
if errorlevel 1 goto fail_pip
echo [OK]   Python packages

REM ---- Optional Python packages: named one by one, because "install the
REM      requirements" tells nobody which feature they just lost.
call :soft_check edge_tts      "edge-tts"                 "Persian narration"
call :soft_check faster_whisper "faster-whisper"          "subtitles for video you filmed yourself"
call :soft_check cv2           "opencv-python-headless"   "face-aware zoom and subtitle placement"
call :soft_check piper         "piper-tts"                "offline Persian narration (no internet needed)"
call :soft_check noisereduce   "noisereduce"              "the spectral noise remover (fallback)"
call :soft_check soundfile     "soundfile"                "reading audio for noise removal"

REM ---- Database
pushd "%BACKEND%"
python manage.py check >nul 2>"%LOGDIR%\check.err"
if errorlevel 1 (
    popd
    goto fail_django_check
)
python manage.py migrate --noinput >nul 2>"%LOGDIR%\migrate.err"
if errorlevel 1 (
    popd
    goto fail_migrate
)
python manage.py shell -c "from django.contrib.auth.models import User; User.objects.filter(is_superuser=True).exists() or User.objects.create_superuser('admin','','admin1234')" >nul 2>nul
REM ---- Offline sound: the Persian and English narrators that need no internet
REM      (every Piper voice the admin rows name, not only the defaults), the
REM      DeepFilterNet noise remover, and the library of real recordings (rain,
REM      street, steps...) - indexed from disk first, fetched only if missing.
REM      Which engine is used is chosen in the admin (Audio engines); this only
REM      makes sure the offline ones exist. Downloaded once, then offline.
REM      Voices come from Hugging Face, or its mirror when HF refuses the
REM      connection; set HF_ENDPOINT in the environment to use another mirror.
python manage.py audio_setup --check >"%LOGDIR%\audio.txt" 2>&1
if not errorlevel 1 goto audio_ok
type "%LOGDIR%\audio.txt"
call :ask "Download what is missing now? Up to about 300 MB, once."
if /i not "%ANSWER%"=="y" goto audio_skipped
python manage.py audio_setup --english
python manage.py audio_setup --check >"%LOGDIR%\audio.txt" 2>&1
if not errorlevel 1 goto audio_ok
echo [WARN] Some offline sound pieces are still missing - see logs\audio.txt
echo        Retry later with:  cd backend ^& python manage.py audio_setup
goto audio_done
:audio_skipped
echo [INFO] Skipped. Online voices still work; run start.bat again to download.
goto audio_done
:audio_ok
echo [OK]   Offline voices, noise removal and sound library
:audio_done
popd
echo [OK]   Database ready — admin / admin1234

REM ---- Frontend
if not exist "%FRONTEND%\node_modules\.bin\vite.cmd" (
    echo [setup] Installing dashboard packages, please wait...
    pushd "%FRONTEND%"
    if exist "node_modules" rmdir /s /q node_modules
    call npm install --no-audit --no-fund
    popd
)
if not exist "%FRONTEND%\node_modules\.bin\vite.cmd" goto fail_frontend
echo [OK]   Dashboard packages

REM ---- Website (optional)
if not "%START_WEBSITE%"=="1" goto website_done
if not exist "%WEBSITE%\package.json" goto website_missing
if exist "%WEBSITE%\node_modules\.bin\next.cmd" goto website_env
echo [setup] Installing website packages ^(first run, may take a while^)...
pushd "%WEBSITE%"
call npm install --no-audit --no-fund
popd
if not exist "%WEBSITE%\node_modules\.bin\next.cmd" goto website_missing
:website_env
if exist "%WEBSITE%\.env.local" goto website_ok
if not exist "%WEBSITE%\.env.example" goto website_ok
copy /y "%WEBSITE%\.env.example" "%WEBSITE%\.env.local" >nul
:website_ok
REM Before the build: the key has to exist in website/.env.*.local when Next
REM reads its environment, not after.
call :pin_revalidate_secret
echo [OK]   Website packages
if "%WEBSITE_DEV%"=="1" echo [OK]   Website on its dev server — live reload, slow first visits
REM The build itself waits until section 6, once Django is answering.
REM See :website_build.
goto website_done
:website_missing
echo [WARN] Public website unavailable — dashboard only.
set "START_WEBSITE=0"
:website_done

if "%INSTALL_ONLY%"=="1" (
    echo.
    echo  ============================================
    echo    Install finished. Run start.bat to launch.
    echo  ============================================
    pause
    exit /b 0
)

REM ============================================================
REM  4. WHICH AI RUNS HERE, AND WHICH GOES TO AN API
REM
REM  Asked once, separately for text, image and video. Whatever goes to an
REM  API, its local engine is never launched — but an API for VIDEO must not
REM  switch off ComfyUI if IMAGE is still local, which is exactly why the
REM  three are asked separately.
REM
REM  Django is the single source of truth. Deciding it here as well would be a
REM  second place free to drift from the first.
REM ============================================================
echo.
pushd "%BACKEND%"
if "%FORCE_SETUP%"=="1" (
    python manage.py aisetup
) else (
    python manage.py aisetup --if-unset
)
set "AI_NEEDS="
for /f "usebackq tokens=*" %%m in (`python manage.py aimode --needs 2^>nul`) do set "AI_NEEDS=%%m"
popd

set "NEED_OLLAMA=0"
set "NEED_COMFY=0"
echo %AI_NEEDS% | findstr /c:"ollama"  >nul && set "NEED_OLLAMA=1"
echo %AI_NEEDS% | findstr /c:"comfyui" >nul && set "NEED_COMFY=1"

if "%NEED_OLLAMA%%NEED_COMFY%"=="00" (
    echo [OK]   AI: everything through APIs — no local GPU needed
) else (
    echo [OK]   Engines needed on this machine: %AI_NEEDS%
    echo        Change it later with:  start.bat /setup
)

REM ---- Now that we know, the missing-Ollama warning can be accurate.
if "%NEED_OLLAMA%"=="1" if "%HAS_OLLAMA%"=="0" (
    echo [WARN] You chose LOCAL for text/vision but Ollama is not installed.
    echo        Either install it from ollama.com, point OLLAMA_BASE_URL in
    echo        backend\.env at another machine, or run: start.bat /setup
)

REM ---- ComfyUI only matters if image or video is local.
if "%NEED_COMFY%"=="1" goto comfy_needed
set "COMFYUI_DIR="
echo [OK]   Image/video through an API — ComfyUI not needed
goto comfy_done
:comfy_needed
if "%COMFYUI_DIR%"=="" call :find_comfyui
if not "%COMFYUI_DIR%"=="" goto comfy_found
echo [WARN] You chose LOCAL for image/video but ComfyUI was not found.
echo        Set COMFYUI_DIR at the top of this file, point
echo        COMFYUI_BASE_URL in backend\.env at another machine,
echo        or run: start.bat /setup
goto comfy_done
:comfy_found
echo [OK]   ComfyUI: %COMFYUI_DIR%
REM ---- Lip-sync: only scenes marked "presenter speaks on camera" use it.
REM      The node goes into ComfyUI's custom_nodes, its packages into
REM      ComfyUI's own Python, the LatentSync model (about 5 GB) next to it.
pushd "%BACKEND%"
python manage.py lipsync_setup --check --comfyui-dir "%COMFYUI_DIR%" >"%LOGDIR%\lipsync.txt" 2>&1
if not errorlevel 1 goto lipsync_ok
type "%LOGDIR%\lipsync.txt"
call :ask "Install lip-sync for speaking presenters? About 5 GB, once."
if /i not "%ANSWER%"=="y" goto lipsync_skipped
python manage.py lipsync_setup --english --comfyui-dir "%COMFYUI_DIR%"
goto lipsync_done
:lipsync_skipped
echo [INFO] Skipped. Voice-over videos are not affected; run start.bat again to install.
goto lipsync_done
:lipsync_ok
echo [OK]   Lip-sync node and model for ComfyUI
:lipsync_done
popd
:comfy_done

REM ---- Ports already taken?
call :port_busy 8000 "Backend"
call :port_busy 5173 "Dashboard"
if "%START_WEBSITE%"=="1" call :port_busy 3001 "Website"

REM ============================================================
REM  5. SELF-CHECK (never blocks)
REM ============================================================
if "%SKIP_SELFTEST%"=="1" goto selfcheck_done

echo.
echo  --------------------------------------------------------
echo    Self-check — the app against simulated models.
echo    Skip with:  start.bat /notest
echo  --------------------------------------------------------

pushd "%BACKEND%"
python manage.py selftest --quick >"%LOGDIR%\selftest.log" 2>&1
if errorlevel 1 (
    set "SELFCHECK_FAILED=1"
    echo [WARN] Pipeline self-check failed — logs\selftest.log
) else (
    echo [OK]   Pipeline self-check passed
)

if "%HAS_REDIS%"=="1" (
    python tools\e2e_api_test.py --queue >"%LOGDIR%\e2e.log" 2>&1
) else (
    python tools\e2e_api_test.py >"%LOGDIR%\e2e.log" 2>&1
)
if errorlevel 1 (
    set "SELFCHECK_FAILED=1"
    echo [WARN] API end-to-end check failed — logs\e2e.log
) else (
    echo [OK]   API end-to-end check passed
)
popd

if defined SELFCHECK_FAILED (
    echo.
    echo  ---- last lines of the failing check ----
    powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGDIR%\selftest.log' -Tail 8 -Encoding UTF8" 2>nul
    powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGDIR%\e2e.log' -Tail 8 -Encoding UTF8" 2>nul
    echo  -----------------------------------------
    echo [WARN] Starting anyway — these are warnings, not blockers.
)
:selfcheck_done

REM ============================================================
REM  6. LAUNCH
REM ============================================================
echo.
echo  ============================================
echo    Starting services
echo  ============================================
echo.

if "%NEED_OLLAMA%"=="1" if "%START_OLLAMA%"=="1" if "%HAS_OLLAMA%"=="1" (
    echo [run] Ollama        :11434
    REM One model loaded at a time, released after 30s. The GPU is the binding
    REM constraint, and Ollama holding a 20 GB model resident is 20 GB ComfyUI
    REM cannot have.
    set "OLLAMA_FLASH_ATTENTION=1"
    set "OLLAMA_NUM_PARALLEL=1"
    set "OLLAMA_CONTEXT_LENGTH=8192"
    set "OLLAMA_KV_CACHE_TYPE=q8_0"
    set "OLLAMA_MAX_LOADED_MODELS=1"
    set "OLLAMA_KEEP_ALIVE=30s"
    set "OLLAMA_GPU_OVERHEAD=500000000"
    start "UpMarket — Ollama" cmd /k "ollama serve"
)

if not "%COMFYUI_DIR%"=="" if exist "%COMFYUI_DIR%" (
    echo [run] ComfyUI       :8188
    start "UpMarket — ComfyUI" /d "%COMFYUI_DIR%" cmd /k "%COMFYUI_CMD%"
)

if "%HAS_REDIS%"=="1" (
    echo [run] Redis         :6379
    REM The start line is a subroutine and not a line here, on purpose.
    REM :start_redis says why. The short version: the path in REDIS_CMD can
    REM close this block early and take the whole launcher down with it.
    call :start_redis
    call :wait_for_redis
)

echo [run] Backend       :8000
start "UpMarket — Backend" /d "%BACKEND%" cmd /k "python manage.py runserver 0.0.0.0:8000"

if "%HAS_REDIS%"=="1" (
    echo [run] Celery workers
    REM Two queues, one window. `ai` and `gpu` are separate so a long render
    REM cannot block a caption that takes two seconds.
    start "UpMarket — Celery" /d "%BACKEND%" cmd /k "timeout /t 5 >nul && start /b celery -A config worker -l info -Q celery,ai --pool=solo -n ai@%%h && celery -A config worker -l info -Q gpu --pool=solo -n gpu@%%h"
)

echo [run] Dashboard     :5173
start "UpMarket — Dashboard" /d "%FRONTEND%" cmd /k "npm run dev"

echo.
echo  Waiting for the backend to answer ...
call :wait_for_url "http://localhost:8000/healthz" 40

REM The website goes last because its pages are built out of what Django
REM serves. Build it while the backend is still down and every generated
REM page quietly gets the fallback copy baked into it — the site comes up
REM fast and wrong, which is worse than coming up slow.
if "%START_WEBSITE%"=="1" (
    call :website_build
    echo [run] Website       :3001
    call :start_website
)

REM ============================================================
REM  7. HEALTH CHECK
REM ============================================================
echo.
echo  ============================================
echo    Health check
echo  ============================================

where curl >nul 2>nul
if errorlevel 1 (
    echo [WARN] curl not available — skipping health checks
    goto summary
)

call :healthcheck "Backend      " "http://localhost:8000/healthz"
call :healthcheck "Backend ready" "http://localhost:8000/readyz"
call :healthcheck "Dashboard    " "http://localhost:5173/"
if "%START_WEBSITE%"=="1" call :healthcheck "Website      " "http://localhost:3001/"
if "%NEED_OLLAMA%"=="1" if "%HAS_OLLAMA%"=="1" call :healthcheck "Ollama       " "http://localhost:11434/"
if not "%COMFYUI_DIR%"=="" if exist "%COMFYUI_DIR%" call :healthcheck "ComfyUI      " "http://127.0.0.1:8188/"

echo.
pushd "%BACKEND%"
python manage.py checkmodels 2>nul
popd

:summary
echo.
echo  ============================================
echo    UpMarket is running
echo  ============================================
echo   Dashboard : http://localhost:5173
if "%START_WEBSITE%"=="1" echo   Website   : http://localhost:3001
echo   API docs  : http://localhost:8000/api/docs/
echo   Admin     : http://localhost:8000/admin/   admin / admin1234
echo   Health    : http://localhost:8000/readyz
echo   Engines   : %AI_NEEDS%
echo.
if "%HAS_FFMPEG%"=="0" echo   [!] No ffmpeg — video, voice, subtitles and editing are OFF.
if "%HAS_REDIS%"=="0"  echo   [!] No Redis — video generation is OFF.
echo   Something not working? Run doctor.bat — it checks every service,
echo   the queue, the AI engines and the public site in one pass and
echo   writes logs\doctor.txt.
if "%WEBSITE_DEV%"=="1" echo   [!] Website is on its dev server — the first visit to
if "%WEBSITE_DEV%"=="1" echo       each page takes seconds. Drop /sitedev for the built site.
echo.
echo   A service showing WARN has its own window — the exact error is there.
echo   Logs: %LOGDIR%
echo.
start http://localhost:5173
pause
exit /b 0


REM ============================================================
REM  HELPERS
REM ============================================================

:show_help
echo.
echo  start.bat            normal run
echo  start.bat /notest    skip the self-check
echo  start.bat /setup     re-ask which AI runs locally and which uses an API
echo  start.bat /install   install missing dependencies, then exit
echo  start.bat /minimal   dashboard + backend only
echo  start.bat /sitedev   serve the public website from its dev server
echo.
pause
exit /b 0

REM ---- Yes/no, defaulting to yes on Enter --------------------------------
:ask
set "ANSWER="
set /p "ANSWER=       %~1 [Y/n] "
if "%ANSWER%"=="" set "ANSWER=y"
if /i "%ANSWER%"=="yes" set "ANSWER=y"
if /i not "%ANSWER%"=="y" set "ANSWER=n"
exit /b 0

REM ---- An optional package, named with what it is for --------------------
REM "install the requirements" tells nobody which feature they just lost.
:soft_check
python -c "import %~1" >nul 2>nul
if not errorlevel 1 (
    echo [OK]   %~2
    exit /b 0
)
echo [MISSING] %~2 — %~3 will not work.
call :ask "Install %~2 now?"
if /i not "%ANSWER%"=="y" exit /b 0
pip install %~2
python -c "import %~1" >nul 2>nul && echo [OK]   %~2 installed
exit /b 0

REM ---- ffmpeg ------------------------------------------------------------
:install_ffmpeg
REM winget is deliberately NOT tried first, which is the opposite of the usual
REM advice. Its ffmpeg package downloads from gyan.dev, and gyan.dev does not
REM resolve from Iran at all — measured, not assumed. For this product's
REM customers that path is several minutes of waiting followed by a failure,
REM so the portable copy below, from GitHub, is the only one offered.
REM
REM If you are somewhere gyan.dev works and you would rather have ffmpeg on the
REM system PATH:  winget install --id Gyan.FFmpeg
:ffmpeg_portable

echo        Downloading a portable copy into the project folder ...
where curl >nul 2>nul
if errorlevel 1 (
    echo [WARN] curl not available — cannot download. Install ffmpeg manually
    echo        from https://ffmpeg.org/download.html
    exit /b 0
)

REM GitHub rather than gyan.dev: the usual ffmpeg host does not resolve from
REM Iran at all, and this product's customers are Iranian shops.
REM
REM --ssl-no-revoke skips the certificate REVOCATION check, not the certificate
REM check. Behind a filtered connection the revocation server is unreachable
REM and curl aborts a perfectly valid handshake with CRYPT_E_REVOCATION_OFFLINE,
REM which tells a shop owner nothing at all.
set "FFZIP=%TEMP%\upmarket-ffmpeg.zip"
set "FFBIN=%ROOT%ffmpeg\bin"
set "FFURL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
curl -L --fail --ssl-no-revoke --max-time 1800 --retry 2 -o "%FFZIP%" "%FFURL%"
if errorlevel 1 (
    echo [WARN] Download failed — usually the connection, not the file.
    echo        Get ffmpeg yourself, put ffmpeg.exe and ffprobe.exe into
    echo        %ROOT%ffmpeg\bin\ and run start.bat again.
    exit /b 0
)

REM Only the two files we need come out of the archive. Unpacking it whole
REM writes about 700 MB to disk in order to keep 60 MB of it — and the machine
REM this was written on had a completely full disk an hour earlier.
REM
REM The entry names carry a version-stamped folder, so they are matched by what
REM they END with rather than by a path we would have to guess.
REM
REM The pipes below are NOT caret-escaped, and must not be: inside double
REM quotes cmd already leaves `|` alone, so `^|` reaches PowerShell as two
REM literal characters and the whole command dies on a parse error — while
REM the batch carries on as if it had worked.
echo        Extracting ffmpeg.exe and ffprobe.exe ...
if not exist "%ROOT%ffmpeg\bin" mkdir "%ROOT%ffmpeg\bin"
powershell -NoProfile -Command ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "$zip=[IO.Compression.ZipFile]::OpenRead($env:FFZIP);" ^
  "foreach($want in 'bin/ffmpeg.exe','bin/ffprobe.exe'){" ^
  "  $e=$zip.Entries | Where-Object { $_.FullName -like ('*'+$want) } | Select-Object -First 1;" ^
  "  if($e){ [IO.Compression.ZipFileExtensions]::ExtractToFile($e,(Join-Path $env:FFBIN $e.Name),$true) }" ^
  "}; $zip.Dispose()" >nul 2>nul

del "%FFZIP%" 2>nul

if exist "%ROOT%ffmpeg\bin\ffmpeg.exe" (
    set "PATH=%ROOT%ffmpeg\bin;%PATH%"
    set "HAS_FFMPEG=1"
    echo [OK]   ffmpeg installed into the project folder
) else (
    echo [WARN] ffmpeg install did not complete.
)
exit /b 0

REM ---- Point .env at the project's own ffmpeg ---------------------------
REM Celery workers do not inherit this window's PATH, so a PATH edit alone
REM would work here and fail inside every render.
REM
REM Three cases, and the middle one is why this is not two lines:
REM
REM   * nothing pinned yet         -> pin it.
REM   * pinned, and the file is there -> leave it alone. Somebody may have
REM     aimed this at another drive or another machine deliberately, and a
REM     launcher that overwrites a deliberate setting is worse company than
REM     one that does nothing.
REM   * pinned, and the file is GONE -> the project folder was moved or
REM     copied, so repair it. Nothing else ever will: the pin still looks
REM     present, so a plain 'is it set?' check skips it, and the damage
REM     surfaces an hour later as a render dying on a path nobody
REM     recognises -- which is exactly how this was found.
:pin_ffmpeg_path
REM .env.local, not .env: the pin is an absolute path that is only true on
REM THIS machine, and .env travels to the other one with every push.
set "ENV_FILE=%BACKEND%\.env.local"
set "FF_EXE=%ROOT%ffmpeg\bin\ffmpeg.exe"
set "FP_EXE=%ROOT%ffmpeg\bin\ffprobe.exe"
if not exist "%ENV_FILE%" (
    >"%ENV_FILE%" echo # تنظیم‌های مخصوص همین سیستم — این فایل کامیت نمی‌شود.
    >>"%ENV_FILE%" echo # هرچه اینجا باشد، روی backend\.env را می‌پوشاند.
)
findstr /b /c:"FFMPEG_BIN=" "%ENV_FILE%" >nul 2>nul || goto pin_ffmpeg_append
REM Written back through .NET rather than Set-Content, because this file
REM carries Persian comments and PowerShell 5.1 would hand it a UTF-8 BOM,
REM which python-dotenv then reads as part of the first name in the file.
powershell -NoProfile -Command "$p=$env:ENV_FILE; $lines=[IO.File]::ReadAllLines($p); $cur=($lines | Where-Object { $_ -like 'FFMPEG_BIN=*' } | Select-Object -First 1); if ($cur -and (Test-Path -LiteralPath $cur.Substring(11).Trim())) { exit 0 }; $out=$lines | ForEach-Object { if ($_ -like 'FFMPEG_BIN=*') { 'FFMPEG_BIN=' + $env:FF_EXE } elseif ($_ -like 'FFPROBE_BIN=*') { 'FFPROBE_BIN=' + $env:FP_EXE } else { $_ } }; try { [IO.File]::WriteAllLines($p, $out, (New-Object Text.UTF8Encoding $false)) } catch { exit 2 }; exit 1"
if errorlevel 2 (
    echo [WARN] backend\.env pins an ffmpeg that is no longer there, and it
    echo        could not be rewritten. Set FFMPEG_BIN and FFPROBE_BIN by hand.
    exit /b 0
)
if errorlevel 1 echo [OK]   ffmpeg in backend\.env repointed here ^(the project had moved^)
exit /b 0

:pin_ffmpeg_append
>>"%ENV_FILE%" echo.
>>"%ENV_FILE%" echo # Written by start.bat — the project's own ffmpeg. Celery workers do not
>>"%ENV_FILE%" echo # inherit the launcher's PATH, so the path is pinned here instead.
>>"%ENV_FILE%" echo FFMPEG_BIN=%FF_EXE%
>>"%ENV_FILE%" echo FFPROBE_BIN=%FP_EXE%
echo [OK]   ffmpeg path written to backend\.env.local (this machine only)
exit /b 0

REM ---- The key Django uses to refresh the public site -------------------
REM
REM Without it, an edit in the Django admin takes up to two minutes to show
REM on the site and looks like it was ignored. The script explains the rest.
:pin_revalidate_secret
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\revalidate-secret.ps1" -Backend "%BACKEND%" -Website "%WEBSITE%" >nul
if errorlevel 1 (
    echo [WARN] Could not set up the site-refresh key. Everything still works;
    echo        admin edits just take up to two minutes to show on the site.
    exit /b 0
)
echo [OK]   Site refresh key in place - admin edits show immediately
exit /b 0

REM ---- Redis, portable, inside the project ------------------------------
:install_redis
where curl >nul 2>nul
if errorlevel 1 (
    echo [WARN] curl not available — cannot download Redis.
    exit /b 0
)
set "RZIP=%TEMP%\upmarket-redis.zip"
echo        Downloading Redis for Windows ^(about 6 MB^) ...
curl -L --fail --ssl-no-revoke --max-time 600 --retry 2 -o "%RZIP%" "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip"
if errorlevel 1 (
    echo [WARN] Download failed. Video generation stays off; everything else works.
    exit /b 0
)
if not exist "%ROOT%redis" mkdir "%ROOT%redis"
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%RZIP%' -DestinationPath '%ROOT%redis' -Force" >nul 2>nul
del "%RZIP%" 2>nul
if exist "%ROOT%redis\redis-server.exe" (
    set "HAS_REDIS=1"
    set "REDIS_CMD=%ROOT%redis\redis-server.exe"
    echo [OK]   Redis installed into the project folder
) else (
    echo [WARN] Redis extraction failed. Video generation stays off.
)
exit /b 0

REM ---- ComfyUI, in the usual places -------------------------------------
:find_comfyui
for %%D in (
    "%ROOT%..\ComfyUI_windows_portable"
    "%ROOT%..\..\ComfyUI_windows_portable"
    "%USERPROFILE%\ComfyUI_windows_portable"
    "%USERPROFILE%\Desktop\ComfyUI_windows_portable"
    "C:\ComfyUI_windows_portable"
    "D:\ComfyUI_windows_portable"
    "E:\ComfyUI_windows_portable"
    "E:\Ai\ComfyUI_windows_portable"
    "C:\ComfyUI"
    "D:\ComfyUI"
    "E:\ComfyUI"
) do (
    if exist "%%~D\%COMFYUI_CMD%" (
        set "COMFYUI_DIR=%%~D"
        goto :eof
    )
)
goto :eof

REM ---- The public website: built once, not compiled per visit ----------
REM The dashboard and the website are both 'the dev server', and they are
REM not the same animal at all. Vite hands the browser modules and lets it
REM assemble them, so a page the dashboard has never shown costs about what
REM one it has already shown costs. `next dev` compiles a route the first
REM time somebody opens it, and the visitor sits through it. Measured on
REM this project: 2 to 5 seconds for every page not visited before, against
REM 10 to 15 MILLISECONDS for the same pages once built. That is the whole
REM of 'the panel is fine but the site is slow'.
REM
REM Nearly every page here is pre-rendered anyway, so the compile was never
REM work the request needed -- it was work the request was made to wait for.
REM
REM So: build it, then serve it. The build costs about a minute, and runs
REM again only when a file under the site is newer than the last one, which
REM is what makes it safe in a launcher people run several times a day.
REM
REM Text typed into the Django admin does NOT need a rebuild. Those pages
REM re-fetch on their own schedule (the `revalidate` in website/lib/api.ts).
REM The build only has to catch up with code and with content/ on disk.
REM
REM This runs after the backend is up, not during setup, because a page
REM generated while Django is down keeps the fallback copy until its own
REM revalidate window expires.
REM
REM Editing the website itself?  start.bat /sitedev  gives back live reload.
:website_build
call :website_build_needed
if not errorlevel 1 (
    echo [OK]   Website already built — pages will be instant
    exit /b 0
)
echo [setup] Building the public website — about a minute. This happens
echo         only when something changed since the last build.
pushd "%WEBSITE%"
call npm run build
popd
if exist "%WEBSITE%\.next\BUILD_ID" (
    echo [OK]   Website built
    exit /b 0
)
REM A website that will not build is not a reason to refuse to start. The
REM dev server renders the same pages, slowly, and shows the error on the
REM page itself -- which is more use to whoever has to fix it than a
REM launcher that simply stopped.
echo [WARN] The website build failed — falling back to the dev server.
echo        Pages will be slow on first visit, and the error will be on
echo        the page and in that window.
set "WEBSITE_DEV=1"
exit /b 0

REM Does anything under the site postdate the last build?
REM
REM node_modules and .next are deliberately not looked at: walking them
REM costs more than the answer is worth, and neither is a source of truth
REM about what the site should look like.
REM
REM The path goes over as an environment variable instead of being pasted
REM into the command, because it can hold spaces and brackets and this is
REM already a quoted string inside a quoted string. Note also that the
REM pipes are NOT caret-escaped -- see :install_ffmpeg for why that matters.
:website_build_needed
if not exist "%WEBSITE%\.next\BUILD_ID" exit /b 1
set "WEB_DIR=%WEBSITE%"
set "WEB_BUILD_ID=%WEBSITE%\.next\BUILD_ID"
powershell -NoProfile -Command "$built=(Get-Item -LiteralPath $env:WEB_BUILD_ID).LastWriteTime; $src=@('app','components','lib','content','public','middleware.ts','next.config.mjs','postcss.config.mjs','package.json','.env.local') | ForEach-Object { Join-Path $env:WEB_DIR $_ } | Where-Object { Test-Path -LiteralPath $_ }; $n=Get-ChildItem -LiteralPath $src -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1; if ($n) { exit 1 } else { exit 0 }"
exit /b %errorlevel%

REM ---- The website, in its own window -----------------------------------
:start_website
if "%WEBSITE_DEV%"=="1" (
    start "UpMarket — Website (dev)" /d "%WEBSITE%" cmd /k "npm run dev"
    exit /b 0
)
start "UpMarket — Website" /d "%WEBSITE%" cmd /k "npm run start"
exit /b 0
REM ---- Redis, in its own window -----------------------------------------
REM This one line is a subroutine because it cannot live inside the
REM `if "%HAS_REDIS%"=="1" (` block that calls it.
REM
REM REDIS_CMD holds a full path, and a project folder is free to have a
REM bracket in its name -- "New folder (2)", the name Windows itself gives
REM a second copy, is a real example. Inside a bracketed block cmd expands
REM the variable BEFORE it goes looking for the block's closing bracket, so
REM the ")" out of the path closes the block early, the rest of the line is
REM left over, and the launcher dies on "was unexpected at this time" --
REM before a single service has started, in a window that shuts too fast to
REM read. At the top level of a subroutine that same bracket is just a
REM character, and the line is safe.
REM
REM The doubled quotes are deliberate too. cmd /k keeps a path quoted only
REM when it is handed MORE than two quote characters; with exactly two it
REM strips them, and a path with a space in it then arrives as fragments.
:start_redis
start "UpMarket — Redis" cmd /k ""%REDIS_CMD%""
exit /b 0

REM ---- Waiting ----------------------------------------------------------
:wait_for_redis
for /l %%i in (1,1,15) do (
    netstat -ano 2>nul | findstr /r /c:":6379 .*LISTENING" >nul && exit /b 0
    "%SystemRoot%\System32\ping.exe" -n 2 127.0.0.1 >nul 2>nul
)
echo [WARN] Redis did not open port 6379 in time.
exit /b 0

REM Polls instead of sleeping a fixed 15 seconds: a fast machine should not
REM wait, and a slow one should not be cut off.
:wait_for_url
where curl >nul 2>nul || (timeout /t 12 /nobreak >nul & exit /b 0)
for /l %%i in (1,1,%~2) do (
    curl -s -o nul --max-time 2 "%~1" 2>nul && exit /b 0
    "%SystemRoot%\System32\ping.exe" -n 2 127.0.0.1 >nul 2>nul
)
exit /b 0

:port_busy
netstat -ano 2>nul | findstr /r /c:":%~1 .*LISTENING" >nul && (
    echo [WARN] Port %~1 is already in use — %~2 may already be running.
)
exit /b 0

:healthcheck
set "HC=000"
for /f %%h in ('curl -s -o nul -w "%%{http_code}" --max-time 6 %~2 2^>nul') do set "HC=%%h"
if "%HC%"=="200" (
    echo [OK]   %~1  %~2
) else (
    echo [WARN] %~1  HTTP %HC% — not ready. %~2
)
exit /b 0

REM ============================================================
REM  FAILURES — each says exactly what to do, and nothing else.
REM ============================================================

:fail_python
echo.
echo [STOP] Python is not installed, or not on your PATH.
echo.
echo        1. Download Python 3.10 or newer from python.org
echo        2. During install, TICK "Add python.exe to PATH"
echo        3. Close this window, open a new one, run start.bat again
echo.
pause
exit /b 1

:fail_node
echo.
echo [STOP] Node.js is not installed, or not on your PATH.
echo.
echo        1. Download Node.js LTS from nodejs.org
echo        2. Close this window, open a new one, run start.bat again
echo.
pause
exit /b 1

:fail_pip
echo.
echo [STOP] The backend packages did not install.
echo.
echo        Usually a network or proxy problem. Try by hand to see the error:
echo          cd backend
echo          pip install -r requirements.txt
echo.
pause
exit /b 1

:fail_frontend
echo.
echo [STOP] The dashboard packages are still broken after a reinstall.
echo.
echo        Try by hand:
echo          cd frontend
echo          rmdir /s /q node_modules
echo          npm cache clean --force
echo          npm install
echo.
pause
exit /b 1

:fail_django_check
echo.
echo [STOP] Django refused to start. This is almost always a setting in
echo        backend\.env — the message below says which one.
echo.
type "%LOGDIR%\check.err" 2>nul
echo.
pause
exit /b 1

:fail_migrate
echo.
echo [STOP] The database migration failed.
echo.
type "%LOGDIR%\migrate.err" 2>nul
echo.
echo        If the database is from an older version, the quickest fix in
echo        development is to delete backend\db.sqlite3 and run start.bat
echo        again — you lose the test data, nothing else.
echo.
pause
exit /b 1
