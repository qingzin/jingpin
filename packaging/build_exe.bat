@echo off
setlocal enabledelayedexpansion

set PY=%~1
if "%PY%"=="" set PY=python

powershell -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1" -Python "%PY%"
if errorlevel 1 (
  echo 打包失败
  exit /b 1
)

echo 打包成功，产物位于 dist\
