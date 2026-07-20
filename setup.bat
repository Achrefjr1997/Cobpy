@echo off
setlocal enabledelayedexpansion

:: =============================================================================
:: COBOL to Python Migrator - Windows Setup Script
:: =============================================================================
:: This script sets up the entire development environment from scratch.
:: After running this, just execute run.bat to start the application.
::
:: Requirements:
::   - Windows 10/11
::   - Python 3.11+
::   - Node.js 18+
::
:: Usage:
::   setup.bat
:: =============================================================================

:: Enable ANSI escape codes (Windows 10 1607+)
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"

:: Colors
set "RED=%ESC%[91m"
set "GREEN=%ESC%[92m"
set "YELLOW=%ESC%[93m"
set "BLUE=%ESC%[94m"
set "CYAN=%ESC%[96m"
set "NC=%ESC%[0m"

:: Project root is where this script lives
set "PROJECT_ROOT=%~dp0"
:: Remove trailing backslash
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

echo.
echo %CYAN%============================================================%NC%
echo %CYAN%  COBOL to Python Migrator - Environment Setup (Windows)%NC%
echo %CYAN%============================================================%NC%
echo.

:: -----------------------------------------------------------------------------
:: Check Python 3.11+
:: -----------------------------------------------------------------------------

echo %BLUE%^> Checking Python...%NC%

python --version >nul 2>&1
if errorlevel 1 (
    echo %RED%X Python is not installed or not on PATH.%NC%
    echo   Please install Python 3.11+ from https://www.python.org/downloads/
    echo   Make sure to check "Add Python to PATH" during installation.
    exit /b 1
)

:: Extract Python version
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)

if %PY_MAJOR% LSS 3 (
    echo %RED%X Python 3.11+ is required, but found %PYVER%%NC%
    exit /b 1
)
if %PY_MAJOR%==3 if %PY_MINOR% LSS 11 (
    echo %RED%X Python 3.11+ is required, but found %PYVER%%NC%
    exit /b 1
)
echo %GREEN%  Python %PYVER% found (^>= 3.11 required)%NC%

:: -----------------------------------------------------------------------------
:: Check Node.js 18+
:: -----------------------------------------------------------------------------

echo.
echo %BLUE%^> Checking Node.js...%NC%

node -v >nul 2>&1
if errorlevel 1 (
    echo %RED%X Node.js is not installed or not on PATH.%NC%
    echo   Please install Node.js 18+ from https://nodejs.org/
    exit /b 1
)

for /f "tokens=1 delims=." %%v in ('node -v') do set "NODE_RAW=%%v"
:: Remove the leading 'v'
set "NODE_MAJOR=%NODE_RAW:v=%"

if %NODE_MAJOR% LSS 18 (
    for /f %%v in ('node -v') do set "NODE_FULL=%%v"
    echo %RED%X Node.js 18+ is required, but found !NODE_FULL!%NC%
    exit /b 1
)
for /f %%v in ('node -v') do echo %GREEN%  Node.js %%v found (^>= 18 required)%NC%

:: Check npm
npm -v >nul 2>&1
if errorlevel 1 (
    echo %RED%X npm is not installed (should come with Node.js)%NC%
    exit /b 1
)
echo %GREEN%  npm is installed%NC%

:: -----------------------------------------------------------------------------
:: Check / Install uv
:: -----------------------------------------------------------------------------

echo.
echo %BLUE%^> Checking uv (Python package manager)...%NC%

uv --version >nul 2>&1
if errorlevel 1 (
    echo %YELLOW%  uv not found. Installing...%NC%
    powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 (
        echo %RED%X Failed to install uv.%NC%
        echo   Please install manually: https://docs.astral.sh/uv/getting-started/installation/
        exit /b 1
    )

    :: Refresh PATH so uv is available in this session
    :: uv installs to %USERPROFILE%\.local\bin or %CARGO_HOME%\bin
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"

    uv --version >nul 2>&1
    if errorlevel 1 (
        echo %RED%X uv was installed but is not on PATH.%NC%
        echo   You may need to restart your terminal, then re-run this script.
        exit /b 1
    )
    echo %GREEN%  uv installed successfully%NC%
) else (
    for /f "delims=" %%v in ('uv --version 2^>^&1') do echo %GREEN%  uv is already installed (%%v)%NC%
)

:: -----------------------------------------------------------------------------
:: Check / Install GnuCOBOL
:: -----------------------------------------------------------------------------

echo.
echo %BLUE%^> Checking GnuCOBOL (COBOL compiler)...%NC%

cobc --version >nul 2>&1
if errorlevel 1 (
    echo %YELLOW%  GnuCOBOL (cobc) not found. Attempting to install via Chocolatey...%NC%
    choco --version >nul 2>&1
    if errorlevel 1 (
        echo %RED%X GnuCOBOL is not installed and Chocolatey is not available.%NC%
        echo   Please install GnuCOBOL manually:
        echo     Option 1: Install Chocolatey ^(https://chocolatey.org/install^) then run: choco install gnucobol
        echo     Option 2: Download from https://www.arnoldtrembley.com/GnuCOBOL.htm
        echo.
        echo %YELLOW%  Continuing without GnuCOBOL - COBOL validation and differential testing will be skipped.%NC%
    ) else (
        choco install gnucobol -y
        cobc --version >nul 2>&1
        if errorlevel 1 (
            echo %YELLOW%  GnuCOBOL installation via Chocolatey did not succeed.%NC%
            echo %YELLOW%  Continuing without it - COBOL validation will be skipped.%NC%
        ) else (
            echo %GREEN%  GnuCOBOL installed successfully via Chocolatey%NC%
        )
    )
) else (
    for /f "delims=" %%v in ('cobc --version 2^>^&1') do (
        echo %GREEN%  %%v%NC%
        goto :cobc_done
    )
    :cobc_done
)

:: -----------------------------------------------------------------------------
:: Setup Backend
:: -----------------------------------------------------------------------------

echo.
echo %BLUE%^> Setting up backend...%NC%

pushd "%PROJECT_ROOT%\backend"

echo   Installing Python dependencies...
uv sync --all-groups
if errorlevel 1 (
    echo %RED%X Failed to install backend dependencies.%NC%
    popd
    exit /b 1
)
echo %GREEN%  Backend dependencies installed%NC%

:: Create .env from .env.example if it doesn't exist
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo %YELLOW%  .env file created from .env.example%NC%
        echo %YELLOW%  Please edit backend\.env and add your API keys!%NC%
    ) else (
        echo %RED%  .env.example not found%NC%
    )
) else (
    echo %GREEN%  .env file already exists%NC%
)

popd

:: -----------------------------------------------------------------------------
:: Setup Frontend
:: -----------------------------------------------------------------------------

echo.
echo %BLUE%^> Setting up frontend...%NC%

pushd "%PROJECT_ROOT%\frontend"

echo   Installing Node.js dependencies...
call npm install
if errorlevel 1 (
    echo %RED%X Failed to install frontend dependencies.%NC%
    popd
    exit /b 1
)
echo %GREEN%  Frontend dependencies installed%NC%

popd

:: -----------------------------------------------------------------------------
:: Create required directories
:: -----------------------------------------------------------------------------

echo.
echo %BLUE%^> Creating required directories...%NC%

if not exist "%PROJECT_ROOT%\logs" (
    mkdir "%PROJECT_ROOT%\logs"
    echo. > "%PROJECT_ROOT%\logs\.gitkeep"
    echo %GREEN%  Created logs\ directory%NC%
) else (
    echo %GREEN%  logs\ directory already exists%NC%
)

if not exist "%PROJECT_ROOT%\data" (
    mkdir "%PROJECT_ROOT%\data"
    echo %GREEN%  Created data\ directory%NC%
) else (
    echo %GREEN%  data\ directory already exists%NC%
)

:: -----------------------------------------------------------------------------
:: Final instructions
:: -----------------------------------------------------------------------------

echo.
echo %CYAN%============================================================%NC%
echo %CYAN%  Setup Complete!%NC%
echo %CYAN%============================================================%NC%
echo.
echo %GREEN%Your environment is ready.%NC%
echo.
echo %YELLOW%Before running the application:%NC%
echo   1. Edit %BLUE%backend\.env%NC% and add your LLM API key
echo      (OpenAI, Anthropic, Google, or xAI)
echo.
echo %YELLOW%To start the application:%NC%
echo   %BLUE%run.bat%NC%              -- Development mode (auto-reload)
echo   %BLUE%run.bat --no-reload%NC%  -- Stable mode (for testing migrations)
echo.
echo %YELLOW%Access the application:%NC%
echo   Frontend: %BLUE%http://localhost:5173%NC%
echo   Backend:  %BLUE%http://localhost:8000%NC%
echo   Health:   %BLUE%http://localhost:8000/health%NC%
echo.

:: Check if .env still has the placeholder key
findstr /C:"sk-your-openai-key" "%PROJECT_ROOT%\backend\.env" >nul 2>&1
if not errorlevel 1 (
    echo %RED%============================================================%NC%
    echo %RED%  WARNING: You must add your API key to backend\.env%NC%
    echo %RED%============================================================%NC%
    echo.
)

echo %GREEN%Happy coding!%NC%
echo.

endlocal
