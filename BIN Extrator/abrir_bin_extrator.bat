@echo off
setlocal
cd /d "%~dp0"

if exist "%LocalAppData%\Programs\Python\Python313\pythonw.exe" (
    start "" "%LocalAppData%\Programs\Python\Python313\pythonw.exe" "%~dp0bin_extrator_gui.py"
    goto :end
)

for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do (
    if exist "%%~fD\pythonw.exe" (
        start "" "%%~fD\pythonw.exe" "%~dp0bin_extrator_gui.py"
        goto :end
    )
)

where py >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 "%~dp0bin_extrator_gui.py"
    goto :end
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0bin_extrator_gui.py"
    goto :end
)

if exist "C:\msys64\mingw64\bin\pythonw.exe" (
    start "" "C:\msys64\mingw64\bin\pythonw.exe" "%~dp0bin_extrator_gui.py"
    goto :end
)

echo Python 3 nao foi encontrado.
pause

:end
endlocal
