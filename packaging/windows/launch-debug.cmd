@echo off
setlocal
call "%~dp0launch-env.cmd"
if errorlevel 1 exit /b %errorlevel%
"%JP2ZH_PORTABLE_ROOT%\runtime\python.exe" "%JP2ZH_PORTABLE_ROOT%\app\scripts\run_gui.py"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
