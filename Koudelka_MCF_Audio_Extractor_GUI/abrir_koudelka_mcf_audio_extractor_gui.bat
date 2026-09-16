@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0koudelka_mcf_audio_extractor_gui.py"
    if errorlevel 1 goto :erro
    goto :fim
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0koudelka_mcf_audio_extractor_gui.py"
    if errorlevel 1 goto :erro
    goto :fim
)

echo Python 3 nao foi encontrado.
echo Instale o Python 3 com suporte ao Tkinter.
pause
goto :fim

:erro
echo.
echo A ferramenta encontrou um erro. A mensagem esta acima.
pause

:fim
endlocal
