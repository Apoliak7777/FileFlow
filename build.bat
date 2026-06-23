@echo off
REM ============================================================
REM  FileFlow — PREMIUM EDITION
REM  One-click build — beautiful single .exe
REM ============================================================

echo.
echo  [1/2] Installing premium dependencies...
python -m pip install --upgrade customtkinter pillow pypdf pyinstaller watchdog pystray

echo.
echo  [2/2] Building FileFlow...
python -m PyInstaller --onefile --windowed --name "FileFlow" ^
  --icon "assets/app.ico" ^
  --collect-all customtkinter ^
  --collect-all watchdog ^
  --collect-all pystray ^
  --collect-all tkinterdnd2 ^
  --add-data "assets;assets" ^
  --clean --noconfirm organizer.py

echo.
echo  ================================================
echo   DONE! Premium build ready:
echo   dist\FileFlow.exe
echo  ================================================
echo.
pause
