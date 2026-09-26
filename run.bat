@echo off
REM Baby Log - starts the app and opens it in its own window.
REM Closing that window does not stop the app: it stays in the notification area, and
REM right-click -> Quit on that icon is what stops it.
cd /d "%~dp0"

REM Re-run ourselves minimised so the console stays out of the way.
if /i not "%~1"=="-started" (
    start "Baby Log launcher" /min "%~f0" -started
    exit /b
)

REM No %* here: our own -started flag must not reach launch.py, which would refuse it.
python launch.py
if errorlevel 1 (
    echo.
    echo The app could not start. The message above says why.
    pause
)
