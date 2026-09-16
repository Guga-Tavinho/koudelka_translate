@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0koudelka_png_to_tex_gui.py"
    if errorlevel 1 goto :erro
    goto :fim
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0koudelka_png_to_tex_gui.py"
    if errorlevel 1 goto :erro
    goto :fim
)

echo Python 3 nao foi encontrado.
pause
goto :fim

:erro
echo.
echo A ferramenta encontrou um erro. A mensagem esta acima.
echo Se o erro mencionar Pillow, execute instalar_dependencias.bat.
pause

:fim
endlocal
