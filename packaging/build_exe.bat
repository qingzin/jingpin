@echo off
setlocal
set PYTHON=%~1
if "%PYTHON%"=="" set PYTHON=python

cd /d %~dp0\..

echo [1/4] 使用解释器: %PYTHON%
%PYTHON% -c "import sys; print(sys.executable)"
if errorlevel 1 goto :error

echo [2/4] 安装依赖
%PYTHON% -m pip install --upgrade pip
if errorlevel 1 goto :error
%PYTHON% -m pip install -r requirements.txt
if errorlevel 1 goto :error
%PYTHON% -m pip install pyinstaller
if errorlevel 1 goto :error

echo [3/4] Qt 环境诊断
%PYTHON% tools\check_qt_env.py
if errorlevel 1 goto :error

echo [4/4] 打包 one-folder EXE
%PYTHON% -m PyInstaller --noconfirm --clean packaging\builder_gui.spec
if errorlevel 1 goto :error
%PYTHON% -m PyInstaller --noconfirm --clean packaging\search_gui.spec
if errorlevel 1 goto :error

echo 完成。产物目录：dist\builder_gui\ 与 dist\search_gui\
exit /b 0

:error
echo 失败，请检查上方日志。
exit /b 1
