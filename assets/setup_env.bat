@echo off
chcp 65001 >nul 2>&1
title RC Plus venv setup

rem ---------------------------------------------------------------
rem  Rebuild the standalone python env used by rcplus_sim.py.
rem
rem  Why this file exists: the WorkBuddy bundled python at
rem  %USERPROFILE%\.workbuddy\binaries\python\... gets reset on
rem  restart, which silently wipes site-packages -- vgamepad
rem  disappears and the virtual gamepad is never created, so the
rem  sim sees no controller. This env lives outside that folder and
rem  survives.
rem
rem  Keep this file ASCII-only (cmd parses it with the console
rem  codepage; non-ASCII would be split into garbled commands).
rem ---------------------------------------------------------------

set VENV=C:\rcplus-env
set PYEXE=%VENV%\Scripts\python.exe

echo [1/3] Creating venv at %VENV% ...
py -3.14 -m venv "%VENV%" >nul 2>&1
if not exist "%PYEXE%" py -3 -m venv "%VENV%" >nul 2>&1
if not exist "%PYEXE%" goto fail

echo [2/3] Upgrading pip ...
"%PYEXE%" -m pip install --disable-pip-version-check -q --upgrade pip

echo [3/4] Installing vgamepad ...
"%PYEXE%" -m pip install --disable-pip-version-check -q vgamepad
if errorlevel 1 goto fail

echo [4/4] Installing pycaw + comtypes (volume wheel) ...
"%PYEXE%" -m pip install --disable-pip-version-check -q pycaw comtypes
if errorlevel 1 goto fail

"%PYEXE%" -c "import vgamepad, pycaw.pycaw, comtypes" >nul 2>&1
if errorlevel 1 goto fail

echo.
echo [OK] Environment ready: %PYEXE%
exit /b 0

:fail
echo.
echo [ERROR] Setup failed.
echo   - Is Python 3.14 installed?  Check with:  py -3.14 -V
echo   - No internet for pip?      Check proxy / firewall.
pause
exit /b 1
