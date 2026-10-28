@echo off
rem NOTE: keep this file ASCII-only. cmd.exe reads .bat in the system
rem codepage (GBK on Chinese Windows), so any Chinese here would be garbled
rem and break parsing. All Chinese messages are printed by the Python side.
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

if not defined PY (
  echo.
  echo   [X] Python not found / Python mei zhuang hao
  echo.
  echo   Please install Python 3.10+ from https://www.python.org/downloads/
  echo   IMPORTANT: tick "Add Python to PATH" during installation.
  echo.
  pause
  exit /b
)

"%PY%" -X utf8 sync.py scan %*
echo.
pause
