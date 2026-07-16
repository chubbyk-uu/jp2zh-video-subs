@echo off
set "JP2ZH_PORTABLE_ROOT=%~dp0"
if "%JP2ZH_PORTABLE_ROOT:~-1%"=="\" set "JP2ZH_PORTABLE_ROOT=%JP2ZH_PORTABLE_ROOT:~0,-1%"

set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
set "HF_HUB_OFFLINE=1"
set "TRANSFORMERS_OFFLINE=1"
set "HF_HOME=%JP2ZH_PORTABLE_ROOT%\cache\huggingface"
set "HF_HUB_CACHE=%JP2ZH_PORTABLE_ROOT%\cache\huggingface\hub"
set "TRANSFORMERS_CACHE=%JP2ZH_PORTABLE_ROOT%\cache\huggingface\transformers"
set "NUMBA_CACHE_DIR=%JP2ZH_PORTABLE_ROOT%\cache\numba"
set "TORCH_HOME=%JP2ZH_PORTABLE_ROOT%\cache\torch"
set "TEMP=%JP2ZH_PORTABLE_ROOT%\cache\temp"
set "TMP=%TEMP%"
set "PATH=%JP2ZH_PORTABLE_ROOT%\bin;%JP2ZH_PORTABLE_ROOT%\runtime;%JP2ZH_PORTABLE_ROOT%\runtime\Scripts;%JP2ZH_PORTABLE_ROOT%\runtime\Lib\site-packages\torch\lib;%SystemRoot%\System32;%SystemRoot%"

if not exist "%JP2ZH_PORTABLE_ROOT%\runtime\python.exe" (
    echo Portable Python runtime is missing:
    echo %JP2ZH_PORTABLE_ROOT%\runtime\python.exe
    exit /b 2
)
