@echo off
rem ASCII only - this is the entry point used by the scheduled task.
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
rem 1) Explicit install paths first (most reliable)
if exist "%USERPROFILE%\anaconda3\python.exe" set "PY=%USERPROFILE%\anaconda3\python.exe"
if not defined PY if exist "%USERPROFILE%\Anaconda3\python.exe" set "PY=%USERPROFILE%\Anaconda3\python.exe"
if not defined PY if exist "C:\ProgramData\anaconda3\python.exe" set "PY=C:\ProgramData\anaconda3\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
rem 2) python from PATH - must actually execute.
rem    The Windows Store alias (WindowsApps\python.exe) is a stub that does
rem    nothing, so we verify with -c before trusting it.
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"

if not defined PY exit /b

"%PY%" -X utf8 sync.py scan --log
