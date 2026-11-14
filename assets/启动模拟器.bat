@echo off
chcp 65001 >nul 2>&1
title RC Plus Gamepad
cd /d "C:/Users/Administrator/WorkBuddy/2026-11-05-03-00-04/rcplus"
"C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe" -u launcher.py
echo.
pause
