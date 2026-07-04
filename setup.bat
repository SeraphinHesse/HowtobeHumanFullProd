@echo off
echo === How To Be Human - Setup ===

:: Check if Python is already available
py --version >nul 2>&1
if %errorlevel% == 0 (
    echo Python already installed.
    goto install_deps
)

python --version >nul 2>&1
if %errorlevel% == 0 (
    echo Python already installed.
    goto install_deps
)

:: Try winget first
echo Python not found. Trying winget...
winget source update >nul 2>&1
winget install --id Python.Python.3.13 -e --source winget
if %errorlevel% == 0 goto python_installed

:: Fallback: download installer directly
echo winget unavailable, downloading Python installer...
powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe' -OutFile '%TEMP%\python_installer.exe'"
"%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1
if %errorlevel% neq 0 (
    echo Python install failed. Please install manually from https://www.python.org/downloads/
    pause
    exit /b 1
)

:python_installed
echo.
echo Python installed. Please close and reopen this window, then run setup.bat again.
echo (PATH needs to refresh for py to be recognised.)
pause
exit /b 0

:install_deps
echo Installing Python dependencies...
py -m pip install -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo pip install failed. See errors above.
    pause
    exit /b 1
)

echo.
echo All done! Run the game with:   py game\main.py
echo Run the editor with:          py editor\main.py
pause
