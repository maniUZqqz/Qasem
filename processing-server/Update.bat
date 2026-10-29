@echo off
title UpMarket - update the processing node
rem ================================================================
rem  Updates THIS folder to the newest code - from the site itself, no git, no questions.
rem  Only the code changes: models, Python environments, the editors and this computer's identity live in the
rem  data folder (%USERPROFILE%\NMarketing-data unless chosen otherwise) and are never touched.
rem  Every replaced file is kept in <data folder>\updates\backup-<time>\ ; if the updated node fails to start
rem  twice, START.bat puts the previous code back by itself.
rem  If START.bat is running it restarts the node on the new code by itself (after the current job).
rem
rem    Update.bat              update now
rem    Update.bat --check      only say whether an update is waiting
rem    Update.bat --rollback   put back the code from before the last update
rem ================================================================
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python was not found. Install Python 3.10+ from python.org and tick "Add python to PATH".
  pause
  exit /b 1
)
:run
(
  python "%~dp0update.py" %*
  if errorlevel 1 (
    echo.
    echo Update did not finish - read the line above. Nothing was changed. Run Update.bat again later.
  ) else (
    echo.
    echo Done. If START.bat is open, the node restarts on the new code by itself; otherwise run START.bat.
  )
  pause
  exit /b 0
)
