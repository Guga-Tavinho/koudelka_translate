@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0koudelka_interface_gui.py"
) else (
    python "%~dp0koudelka_interface_gui.py"
)

if errorlevel 1 (
    echo.
    echo A ferramenta terminou com erro.
    echo Execute instalar_dependencias.bat e tente novamente.
    pause
)
endlocal
