@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0koudelka_tx4_tradutor_gui.py" %*
    if errorlevel 1 pause
    exit /b
)

python "%~dp0koudelka_tx4_tradutor_gui.py" %*
if errorlevel 1 pause
