@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0koudelka_tx8_gui.py" %*
    if errorlevel 1 pause
    exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0koudelka_tx8_gui.py" %*
    if errorlevel 1 pause
    exit /b
)
echo Python 3 nao encontrado. Instale Python com Tcl/Tk e adicione ao PATH.
pause
