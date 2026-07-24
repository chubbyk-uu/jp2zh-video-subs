@echo off
setlocal
call "%~dp0launch-env.cmd"
if errorlevel 1 exit /b %errorlevel%

rem Model downloads must be online even though normal subtitle inference is offline.
set "HF_HUB_OFFLINE="
set "TRANSFORMERS_OFFLINE="

"%JP2ZH_PORTABLE_ROOT%\runtime\python.exe" -m huggingface_hub.cli.hf %*
exit /b %errorlevel%
