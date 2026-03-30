@echo off
setlocal

if "%~1"=="" (
  set PY=python
) else (
  set PY=%~1
)

echo [1/3] Install pyinstaller...
%PY% -m pip install pyinstaller
if errorlevel 1 exit /b 1

echo [2/3] Build builder_tool.exe...
%PY% -m PyInstaller --clean --noconfirm packaging\builder_tool.spec
if errorlevel 1 exit /b 1

echo [3/3] Build search_service.exe...
%PY% -m PyInstaller --clean --noconfirm packaging\search_service.spec
if errorlevel 1 exit /b 1

echo Done. Output under dist\
endlocal
