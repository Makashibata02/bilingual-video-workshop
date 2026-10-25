@echo off
setlocal
cd /d "%~dp0"
if exist "outputs\BilingualVideo-1.9.4\BilingualVideo.exe" (
    start "" "outputs\BilingualVideo-1.9.4\BilingualVideo.exe"
    exit /b
)
if exist "outputs\BilingualVideo-1.9.3\BilingualVideo.exe" (
    start "" "outputs\BilingualVideo-1.9.3\BilingualVideo.exe"
    exit /b
)
if exist "outputs\BilingualVideo-1.9.2\BilingualVideo.exe" (
    start "" "outputs\BilingualVideo-1.9.2\BilingualVideo.exe"
    exit /b
)
if exist "outputs\BilingualVideo-1.9.0\BilingualVideo.exe" (
    start "" "outputs\BilingualVideo-1.9.0\BilingualVideo.exe"
    exit /b
)
if exist "outputs\BilingualVideo-1.8.0\BilingualVideo.exe" (
    start "" "outputs\BilingualVideo-1.8.0\BilingualVideo.exe"
    exit /b
)
if exist "outputs\BilingualVideo-1.7.0\BilingualVideo.exe" (
    start "" "outputs\BilingualVideo-1.7.0\BilingualVideo.exe"
    exit /b
)
if exist "outputs\BilingualVideo-1.6.0\BilingualVideo.exe" (
    start "" "outputs\BilingualVideo-1.6.0\BilingualVideo.exe"
    exit /b
)
if exist "outputs\BilingualVideo-1.5.1\BilingualVideo.exe" (
    start "" "outputs\BilingualVideo-1.5.1\BilingualVideo.exe"
    exit /b
)
if exist "dist\BilingualVideo\BilingualVideo.exe" (
    start "" "dist\BilingualVideo\BilingualVideo.exe"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "app\main.py"
    exit /b
)
echo Please follow README.md to prepare the Python environment first.
pause
