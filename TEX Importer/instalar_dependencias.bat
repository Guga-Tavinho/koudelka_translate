@echo off
setlocal
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m pip install --upgrade Pillow
    goto :fim
)
where python >nul 2>nul
if %errorlevel%==0 (
    python -m pip install --upgrade Pillow
    goto :fim
)
echo Python 3 nao foi encontrado.
:fim
pause
endlocal
