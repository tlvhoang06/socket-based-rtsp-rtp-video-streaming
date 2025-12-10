@echo off
title RTSP Client Launcher

REM ---- Detect Python ----
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found in PATH
    pause
    exit /b
)

set SERVER_ADDR=localhost
set SERVER_PORT=8600
set RTP_PORT=9876
set VIDEO_FILE=movie.Mjpeg

echo Starting client with:
echo   SERVER=%SERVER_ADDR%
echo   PORT=%SERVER_PORT%
echo   RTP=%RTP_PORT%
echo   FILE=%VIDEO_FILE%
echo.

python ClientLauncher.py %SERVER_ADDR% %SERVER_PORT% %RTP_PORT% %VIDEO_FILE%
set EXITCODE=%ERRORLEVEL%

echo.
echo ============================
echo Python exited with code %EXITCODE%
echo ============================
pause
