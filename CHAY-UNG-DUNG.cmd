@echo off
setlocal
cd /d "%~dp0"
where ffmpeg >nul 2>nul
if errorlevel 1 goto missing_ffmpeg
where ffprobe >nul 2>nul
if errorlevel 1 goto missing_ffmpeg
set "APP_PYTHON=.venv\Scripts\python.exe"
if exist "%APP_PYTHON%" goto run_app
if exist "..\..\work\venv\Scripts\python.exe" (
  set "APP_PYTHON=..\..\work\venv\Scripts\python.exe"
  goto run_app
)
python -m venv .venv
if errorlevel 1 goto failed
"%APP_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto failed
:run_app
echo Mo trinh duyet: http://127.0.0.1:8765
echo Giu cua so nay mo khi dung ung dung. Nhan Ctrl+C de dung.
"%APP_PYTHON%" app.py
if errorlevel 1 goto failed
exit /b 0
:missing_ffmpeg
echo Chua tim thay FFmpeg va FFprobe trong PATH. Xem README.md.
pause
exit /b 1
:failed
echo Khong khoi dong duoc. Giu thong bao loi de kiem tra.
pause
exit /b 1
