@echo off
setlocal

set PYTHON=%1
if "%PYTHON%"=="" set PYTHON=python

echo [1/3] Installing dependencies...
%PYTHON% -m pip install -r requirements.txt || exit /b 1
%PYTHON% -m pip install pyinstaller || exit /b 1

echo [2/3] Cleaning old build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] Building GUI executables (one-folder)...
%PYTHON% -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name builder_tool ^
  --hidden-import shiboken6 ^
  --collect-all PySide6 ^
  --collect-all shiboken6 ^
  --add-data "config;config" ^
  builder_gui.py || exit /b 1

%PYTHON% -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name search_gui ^
  --hidden-import shiboken6 ^
  --collect-all PySide6 ^
  --collect-all shiboken6 ^
  --add-data "config;config" ^
  search_gui.py || exit /b 1

echo Build completed.
echo - dist\builder_tool\builder_tool.exe
echo - dist\search_gui\search_gui.exe
endlocal
