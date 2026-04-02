@echo off
setlocal

if "%~1"=="" (
  set PY=python
) else (
  set PY=%~1
)

echo [1/4] Install project requirements...
%PY% -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo [2/4] Install pyinstaller...
%PY% -m pip install pyinstaller
if errorlevel 1 exit /b 1

echo [3/5] Preflight check (Python/PySide6/QtCore)...
%PY% -c "import sys; print('python=', sys.executable); import PySide6, PySide6.QtCore as QtCore; print('PySide6=', PySide6.__file__); print('QtCore=', QtCore.__file__)"
if errorlevel 1 (
  echo PySide6/QtCore import failed. Please ensure this exact Python can import PySide6 before packaging.
  exit /b 1
)

echo [4/5] Build builder_tool.exe...
%PY% -m PyInstaller --clean --noconfirm packaging\builder_tool.spec
if errorlevel 1 exit /b 1

echo [5/5] Build search_gui.exe...
%PY% -m PyInstaller --clean --noconfirm packaging\search_service.spec
if errorlevel 1 exit /b 1

echo Done. Output under dist\
endlocal
