@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title SCR Simulation Web
set "EXIT_CODE=0"
set "PYTHON=.venv\Scripts\python.exe"

echo ========================================
echo   SCR Simulation (Streamlit)
echo ========================================
echo.

if not exist "%PYTHON%" (
    echo [1/3] Creating virtual environment .venv ...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        where python >nul 2>&1
        if errorlevel 1 (
            echo ERROR: Python 3 is not installed.
            echo        https://www.python.org/downloads/
            set "EXIT_CODE=1"
            goto :end
        )
        python -m venv .venv
    )
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        set "EXIT_CODE=1"
        goto :end
    )

    echo [2/3] Installing packages ...
    "%PYTHON%" -m pip install --upgrade pip -q
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install requirements.txt
        set "EXIT_CODE=1"
        goto :end
    )
) else (
    echo [2/3] Checking dependencies ...
    "%PYTHON%" -m pip install -r requirements.txt -q
    if errorlevel 1 (
        echo ERROR: Failed to install requirements.txt
        set "EXIT_CODE=1"
        goto :end
    )
)

echo [3/3] Starting web dashboard ...
echo       Browser will open. Press Ctrl+C here to stop the server.
echo.

"%PYTHON%" -m streamlit run webapp.py
if errorlevel 1 (
    echo.
    echo ERROR: Streamlit failed to start.
    set "EXIT_CODE=1"
)

:end
echo.
if "%EXIT_CODE%"=="0" (
    echo Server stopped.
) else (
    echo Check the error messages above.
)
echo Press any key to close this window ...
pause >nul
exit /b %EXIT_CODE%
