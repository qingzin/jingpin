param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

Write-Host "[1/5] 使用解释器: $Python"
& $Python -c "import sys; print(sys.executable)"

Write-Host "[2/5] 安装依赖"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt
& $Python -m pip install pyinstaller==6.16.0

Write-Host "[3/5] Qt 运行时诊断"
& $Python tools/check_qt_env.py

Write-Host "[4/5] 清理旧产物"
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist) { Remove-Item -Recurse -Force dist }

Write-Host "[5/5] 打包 GUI EXE"
& $Python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/builder_tool.spec
& $Python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/search_gui.spec

Write-Host "完成。产物位于 dist/"
Get-ChildItem dist
