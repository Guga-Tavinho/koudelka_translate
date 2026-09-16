@echo off
cd /d "%~dp0"
python koudelka_legendas_gui_v6.py
if errorlevel 1 pause
