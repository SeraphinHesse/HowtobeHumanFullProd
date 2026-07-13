@echo off
setlocal
echo === How To Be Human - Setup ===

:: --- Locate a Python launcher, prefer the py launcher -----------------------
set "PYCMD="
py --version >nul 2>&1
if %errorlevel% == 0 (
    set "PYCMD=py"
    goto have_python
)
python --version >nul 2>&1
if %errorlevel% == 0 (
    set "PYCMD=python"
    goto have_python
)

:: --- No Python: install it --------------------------------------------------
echo Python not found. Trying winget...
winget source update >nul 2>&1
winget install --id Python.Python.3.13 -e --source winget
if %errorlevel% == 0 goto python_installed

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
echo Python installed. Please CLOSE and REOPEN this window, then run setup.bat again.
echo (PATH needs to refresh for py to be recognised.)
pause
exit /b 0

:have_python
echo Using Python launcher: %PYCMD%
%PYCMD% --version

:: --- Require Python 3.11+ (the game uses 3.11 syntax) -----------------------
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Python 3.11 or newer is required. The launcher above is older.
    echo Install Python 3.13 from https://www.python.org/downloads/ ^(tick "Add to PATH"^),
    echo then reopen this window and run setup.bat again.
    pause
    exit /b 1
)

:: --- Upgrade pip first (old pip is a common source of install warnings) ------
echo.
echo Upgrading pip...
%PYCMD% -m pip install --upgrade pip

:: --- Remove a conflicting plain 'pygame' before installing pygame-ce --------
:: They share the 'pygame' import name; a mixed install imports far enough to
:: reach the main menu, then crashes on gameplay. Uninstall is harmless if
:: plain pygame was never there.
echo.
echo Removing any conflicting 'pygame' package (safe if not present)...
%PYCMD% -m pip uninstall -y pygame >nul 2>&1

:: --- Install the dependencies -----------------------------------------------
echo.
echo Installing Python dependencies...
%PYCMD% -m pip install --upgrade -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo.
    echo pip install FAILED. See the errors above.
    pause
    exit /b 1
)

:: --- Verify the environment can actually run the game -----------------------
echo.
echo Verifying installation...
%PYCMD% "%~dp0tools\doctor.py"
if %errorlevel% neq 0 (
    echo.
    echo Setup finished but the doctor found problems ^(see [FAIL] lines above^).
    echo The game will not run correctly until they are fixed.
    pause
    exit /b 1
)

echo.
echo All done! Run the game with:   py game\main.py
echo Run the editor with:          py editor\main.py
pause
