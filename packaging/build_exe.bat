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

echo [4/4] Copying VC runtime DLLs (if available)...
for /f "delims=" %%i in ('%PYTHON% -c "import sys; print(sys.executable)"') do set PYEXE=%%i
for %%i in ("%PYEXE%") do set PYDIR=%%~dpi

call :copy_runtime vcruntime140.dll
call :copy_runtime vcruntime140_1.dll
call :copy_runtime msvcp140.dll
call :copy_runtime msvcp140_1.dll
call :copy_runtime msvcp140_2.dll

echo Build completed.
echo - dist\builder_tool\builder_tool.exe
echo - dist\search_gui\search_gui.exe
endlocal
exit /b 0

:copy_runtime
set DLLNAME=%1
set SRC=
if exist "%PYDIR%%DLLNAME%" set SRC=%PYDIR%%DLLNAME%
if not defined SRC if exist "%PYDIR%DLLs\%DLLNAME%" set SRC=%PYDIR%DLLs\%DLLNAME%
if defined SRC (
  copy /y "%SRC%" "dist\builder_tool\%DLLNAME%" >nul
  copy /y "%SRC%" "dist\search_gui\%DLLNAME%" >nul
)
exit /b 0
