@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%USERPROFILE%\anaconda3\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" mail_assistant.py
echo.
echo 程序已退出，按任意键关闭窗口…
pause >nul
