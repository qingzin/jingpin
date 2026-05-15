param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

Write-Host "[1/4] 使用解释器: $Python"
& $Python -c "import sys; print(sys.executable)"

Write-Host "[2/4] 安装依赖"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt
& $Python -m pip install pyinstaller

Write-Host "[3/4] Qt 环境诊断"
& $Python tools/check_qt_env.py

Write-Host "[4/4] 打包 one-folder EXE"
& $Python -m PyInstaller --noconfirm --clean packaging/builder_gui.spec
& $Python -m PyInstaller --noconfirm --clean packaging/search_gui.spec

Write-Host "完成。产物目录：dist/builder_gui/ 与 dist/search_gui/"
