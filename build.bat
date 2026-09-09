@echo off
setlocal
cd /d "%~dp0"
echo === GameTrack - installation et compilation ===
where py >nul 2>nul
if errorlevel 1 (
  echo Python n'est pas installe ou absent du PATH.
  pause
  exit /b 1
)
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist GameTrack.spec del /q GameTrack.spec
python -m PyInstaller --noconfirm --clean --onefile --windowed --name GameTrack --add-data "web;web" app.py
if errorlevel 1 (
  echo.
  echo ECHEC DE LA COMPILATION.
  pause
  exit /b 1
)
echo.
echo === TERMINE ===
echo EXE : %CD%\dist\GameTrack.exe
pause

