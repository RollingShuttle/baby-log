@echo off
REM Builds "Baby Log.exe" - one file, no console window.
REM It lands in THIS folder, beside config.yaml and data\, because those are yours and the app
REM looks for them next to itself. Only needed when the code changes.
REM
REM The icon and static paths are absolute because --specpath moves the build directory and
REM PyInstaller resolves relative paths against it, not against this file.
cd /d "%~dp0"

python -m pip install --quiet --disable-pip-version-check pyinstaller
if errorlevel 1 goto :fail

python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name "Baby Log" ^
  --icon "%~dp0icon.ico" ^
  --add-data "%~dp0static;static" ^
  --add-data "%~dp0docs\core.js;docs" ^
  --hidden-import pystray._win32 ^
  --distpath "%~dp0." ^
  --workpath "%~dp0build" ^
  --specpath "%~dp0build" ^
  launch.py
if errorlevel 1 goto :fail

echo.
echo Built: "Baby Log.exe"
echo Run  python tools\make_shortcut.py  to point the Desktop icon at it.
pause
exit /b 0

:fail
echo.
echo The build failed. The messages above say why.
pause
exit /b 1
