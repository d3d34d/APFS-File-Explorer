@echo off
title APFS File Explorer for Windows
cd /d "%~dp0"

echo ===================================================
echo     APFS File Explorer for Windows Launcher
echo ===================================================
echo.

:: Check for Administrator permissions
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] Running with Administrator privileges.
    echo [OK] Raw physical disk access enabled.
    echo.
    echo Starting APFS Desktop Explorer...
    if exist "APFS_Explorer.exe" (
        start "" "APFS_Explorer.exe"
    ) else (
        python gui_explorer.py
    )
) else (
    echo [INFO] Administrator rights required for physical disk access.
    echo [INFO] Requesting elevation via Windows UAC...
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

pause
