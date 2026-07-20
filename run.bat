@echo off
setlocal enabledelayedexpansion

:: =============================================================================
:: COBOL to Python Migrator - Windows Run Script
:: =============================================================================
:: Starts both backend (FastAPI) and frontend (Vite) in separate windows.
::
:: Usage:
::   run.bat              -- Run with auto-reload (development)
::   run.bat --no-reload  -- Run without auto-reload (stable mode)
:: =============================================================================

:: Enable ANSI escape codes (Windows 10 1607+)
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"

:: Colors
set "RED=%ESC%[91m"
set "GREEN=%ESC%[92m"
set "YELLOW=%ESC%[93m"
set "BLUE=%ESC%[94m"
set "NC=%ESC%[0m"

:: Project root is where this script lives
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"

:: -----------------------------------------------------------------------------
:: Parse arguments
:: -----------------------------------------------------------------------------

set "USE_RELOAD=--reload"
set "MODE_LABEL=Development (auto-reload enabled)"

if "%~1"=="--no-reload" (
    set "USE_RELOAD="
    set "MODE_LABEL=Stable (no auto-reload)"
    echo %YELLOW%Running WITHOUT auto-reload (stable mode for testing migrations)%NC%
)
if "%~1"=="-n" (
    set "USE_RELOAD="
    set "MODE_LABEL=Stable (no auto-reload)"
    echo %YELLOW%Running WITHOUT auto-reload (stable mode for testing migrations)%NC%
)

echo.
echo %GREEN%========================================%NC%
echo %GREEN%  COBOL to Python Migrator - Dev Mode%NC%
echo %GREEN%========================================%NC%
echo.

:: -----------------------------------------------------------------------------
:: Check prerequisites are available
:: -----------------------------------------------------------------------------

uv --version >nul 2>&1
if errorlevel 1 (
    echo %RED%X uv is not installed. Please run setup.bat first.%NC%
    exit /b 1
)

node -v >nul 2>&1
if errorlevel 1 (
    echo %RED%X Node.js is not installed. Please run setup.bat first.%NC%
    exit /b 1
)

:: -----------------------------------------------------------------------------
:: Start Backend in a new window
:: -----------------------------------------------------------------------------

echo %BLUE%Starting backend on port %BACKEND_PORT%...%NC%

if defined USE_RELOAD (
    start "COBOL Migrator - Backend" cmd /k "cd /d "%PROJECT_ROOT%\backend" && uv run python run_backend.py --reload"
) else (
    start "COBOL Migrator - Backend" cmd /k "cd /d "%PROJECT_ROOT%\backend" && uv run python run_backend.py"
)

echo %GREEN%  Backend starting in a new window...%NC%

:: Give the backend a moment to start
timeout /t 3 /nobreak >nul

:: -----------------------------------------------------------------------------
:: Start Frontend in a new window
:: -----------------------------------------------------------------------------

echo %BLUE%Starting frontend on port %FRONTEND_PORT%...%NC%

start "COBOL Migrator - Frontend" cmd /k "cd /d "%PROJECT_ROOT%\frontend" && npm run dev"

echo %GREEN%  Frontend starting in a new window...%NC%

:: Give the frontend a moment to start
timeout /t 2 /nobreak >nul

:: -----------------------------------------------------------------------------
:: Print status
:: -----------------------------------------------------------------------------

echo.
echo %GREEN%========================================%NC%
echo %GREEN%  Servers are running!%NC%
echo %GREEN%========================================%NC%
echo.
echo   Backend:  %BLUE%http://localhost:%BACKEND_PORT%%NC%
echo   Frontend: %BLUE%http://localhost:%FRONTEND_PORT%%NC%
echo   Health:   %BLUE%http://localhost:%BACKEND_PORT%/health%NC%
echo   Mode:     %YELLOW%!MODE_LABEL!%NC%
echo.
echo   Backend and frontend are running in separate windows.
echo   Close those windows to stop the servers, or use the
echo   commands below.
echo.
echo %YELLOW%To stop all servers, press any key in this window.%NC%
echo.

:: -----------------------------------------------------------------------------
:: Wait for user to press a key, then clean up
:: -----------------------------------------------------------------------------

pause >nul

echo.
echo %YELLOW%Shutting down servers...%NC%

:: Kill any processes on the backend port
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":%BACKEND_PORT% " ^| findstr "LISTENING"') do (
    echo %BLUE%  Stopping backend process (PID: %%p)...%NC%
    taskkill /PID %%p /F >nul 2>&1
)

:: Kill any processes on the frontend port
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":%FRONTEND_PORT% " ^| findstr "LISTENING"') do (
    echo %BLUE%  Stopping frontend process (PID: %%p)...%NC%
    taskkill /PID %%p /F >nul 2>&1
)

:: Also close the named windows if still open
taskkill /FI "WINDOWTITLE eq COBOL Migrator - Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq COBOL Migrator - Frontend*" /F >nul 2>&1

echo %GREEN%Cleanup complete.%NC%
echo.

endlocal
