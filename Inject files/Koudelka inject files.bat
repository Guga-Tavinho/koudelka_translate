@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0koudelka_inject_arquivo_gui.py"
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0koudelka_inject_arquivo_gui.py"
    goto :end
)

echo Python 3 nao foi encontrado.
pause

:end
endlocal
