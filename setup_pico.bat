@echo off
rem PRJ-022 Grade Scanner - put the firmware on the Pico over the USB cable.
rem Plug the Pico into the laptop, close Thonny, then double-click this file.
setlocal
cd /d "%~dp0"
title PRJ-022 Grade Scanner - Pico setup

if exist ".venv\Scripts\python.exe" goto have_env
set "PY="
python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY py -3 -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo PROBLEM: Python 3.10 or newer was not found.
    echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    goto done
)
echo Creating the Python environment in the .venv folder...
%PY% -m venv .venv || goto done

:have_env
".venv\Scripts\python.exe" -c "import mpremote, serial" >nul 2>&1
if not errorlevel 1 goto run
echo Installing the Pico tools...
".venv\Scripts\python.exe" -m pip install mpremote pyserial || goto done

:run
".venv\Scripts\python.exe" pc\pico_setup.py

:done
echo.
pause
