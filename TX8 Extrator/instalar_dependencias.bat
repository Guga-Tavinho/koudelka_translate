@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m pip install Pillow
    pause
    exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
    python -m pip install Pillow
    pause
    exit /b
)
echo Python 3 nao encontrado. Instale Python com Tcl/Tk e adicione ao PATH.
pause
