@echo off
rem PRJ-022 Grade Scanner - start the marking website.
rem Double-click this file. The first run installs everything it needs.
setlocal
cd /d "%~dp0"
title PRJ-022 Grade Scanner - server

if exist ".venv\Scripts\python.exe" goto have_env
set "PY="
python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY py -3 -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo PROBLEM: Python 3.10 or newer was not found.
    echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    goto fail
)
echo First run: creating the Python environment in the .venv folder...
%PY% -m venv .venv || goto fail

:have_env
fc requirements.txt ".venv\requirements.installed" >nul 2>&1
if not errorlevel 1 goto run
echo Installing the add-ons. This happens once and can take several minutes...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto fail
copy /y requirements.txt ".venv\requirements.installed" >nul

:run
echo.
echo Starting the website at http://127.0.0.1:8022
echo Keep this window open while you use it. Press Ctrl+C here to stop.
echo.
set "OPEN=--open"
if defined PRJ022_NO_BROWSER set "OPEN="
".venv\Scripts\python.exe" pc\server.py %OPEN%
if errorlevel 1 goto fail
goto :eof

:fail
echo.
echo The server did not start. Read the message above, fix it, then run this file again.
pause
exit /b 1
