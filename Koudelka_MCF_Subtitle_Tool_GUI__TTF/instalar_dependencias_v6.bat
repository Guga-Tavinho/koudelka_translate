@echo off
cd /d "%~dp0"
python -m pip install -r requirements_koudelka_v6.txt
echo.
echo Dependencias Python instaladas.
echo Para OCR japones: Tesseract + jpn.traineddata.
pause
