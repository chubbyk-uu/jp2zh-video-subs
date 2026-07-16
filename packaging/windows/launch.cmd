@echo off
setlocal
call "%~dp0launch-env.cmd"
if errorlevel 1 goto runtime_error

if not exist "%JP2ZH_PORTABLE_ROOT%\app\scripts\run_gui.py" (
    echo Application files are missing:
    echo %JP2ZH_PORTABLE_ROOT%\app\scripts\run_gui.py
    pause
    exit /b 3
)

start "" /D "%JP2ZH_PORTABLE_ROOT%" "%JP2ZH_PORTABLE_ROOT%\runtime\pythonw.exe" "%JP2ZH_PORTABLE_ROOT%\app\scripts\run_gui.py"
exit /b 0

:runtime_error
pause
exit /b 2
