@echo off
setlocal
set "BLENDER_EXE=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
if not exist "%BLENDER_EXE%" (
    echo Blender was not found at "%BLENDER_EXE%".
    echo Edit BLENDER_EXE in this launcher to point to Blender 5.2.
    pause
    exit /b 1
)
if "%~1"=="" (
    "%BLENDER_EXE%" --python "%~dp0tools\load_dev_addon.py"
) else (
    "%BLENDER_EXE%" "%~f1" --python "%~dp0tools\load_dev_addon.py"
)
if errorlevel 1 pause
