@echo off
setlocal EnableDelayedExpansion

set "MELT_ENV_FILE=%~dp0..\.env"
set "MELT_LOCALE_DIR=%~dp0..\locales"

if exist "%~dp0..\.venv\Scripts\python.exe" (
    "%~dp0..\.venv\Scripts\python.exe" "%~dp0melt-capture" %*
    exit /b !ERRORLEVEL!
)

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    py -3 "%~dp0melt-capture" %*
    exit /b !ERRORLEVEL!
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python "%~dp0melt-capture" %*
    exit /b !ERRORLEVEL!
)

echo Python 3 was not found. Install Python, then retry. 1>&2
exit /b 1
