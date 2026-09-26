@echo off
REM Baby Log - put this computer's changes on GitHub, and so on the phones and other PCs.
REM Asks one question, runs the tests, commits and pushes. Safe to run any time: it says so
REM and stops when there is nothing to push.
cd /d "%~dp0"

set "msg="
set /p msg=What changed? (one line, no quotes; just press Enter for an automatic note):
python tools\push.py %msg%
if errorlevel 1 (
    echo.
    echo Nothing was pushed. The message above says why.
)
echo.
pause
