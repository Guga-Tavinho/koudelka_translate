@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m pip install --upgrade pillow
) else (
    python -m pip install --upgrade pillow
)

echo.
if errorlevel 1 (
    echo Nao foi possivel instalar o Pillow.
) else (
    echo Dependencias instaladas com sucesso.
)
pause
endlocal
