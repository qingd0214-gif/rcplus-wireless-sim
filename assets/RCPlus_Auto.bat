@echo off
rem ===== RC Plus 常驻手柄开机自启（最小化窗口） =====
rem 1) 把下面两个路径改成你自己的
rem 2) 本文件放进 shell:startup（Win+R 输入 shell:startup 回车）

set SCRIPT_DIR=C:\rcplus-wireless-sim\scripts
set PYTHON=C:\Python313\python.exe

cd /d "%SCRIPT_DIR%"
start "RCPlus" /min "%PYTHON%" -u launcher.py --auto
