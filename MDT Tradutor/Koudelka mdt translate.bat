@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0koudelka_mdt_gui.py" %*
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0koudelka_mdt_gui.py" %*
    goto :end
)

echo Python 3 nao foi encontrado.
echo Instale o Python 3 com o componente Tcl/Tk e tente novamente.
pause

:end
endlocal
