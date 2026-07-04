@echo off
py "%~dp0editor\main.py"
if %errorlevel% neq 0 (
    echo.
    echo Editor exited with an error. See above.
    pause
)
