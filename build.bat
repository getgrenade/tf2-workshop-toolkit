@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build.ps1"
set "BUILD_RESULT=%ERRORLEVEL%"
if not "%BUILD_RESULT%"=="0" echo Build failed. See the error above.
if /I not "%~1"=="--no-pause" pause
exit /b %BUILD_RESULT%
