@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\toolbox_launcher.ps1" -Action Start
set "result=%ERRORLEVEL%"
if not "%result%"=="0" pause
exit /b %result%
