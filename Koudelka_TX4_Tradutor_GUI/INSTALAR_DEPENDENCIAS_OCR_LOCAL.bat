@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    call :instalar py -3
    exit /b
)

where python >nul 2>nul
if %errorlevel%==0 (
    call :instalar python
    exit /b
)

echo Python nao foi encontrado. Instale Python 3.10 ou mais recente e marque "Add Python to PATH".
pause
exit /b 1

:instalar
echo Instalando PyTorch para CPU...
%* -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto :falha

echo Instalando Pillow e EasyOCR...
%* -m pip install -r "%~dp0requirements_koudelka_tx4_gui.txt"
if errorlevel 1 goto :falha

echo.
echo Instalacao concluida. O modelo de OCR sera baixado gratuitamente no primeiro uso.
pause
exit /b 0

:falha
echo.
echo Falha na instalacao. Confira a conexao e a versao do Python.
pause
exit /b 1
