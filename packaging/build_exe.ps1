param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

Write-Host "[1/3] Installing dependencies..."
& $Python -m pip install -r requirements.txt
& $Python -m pip install pyinstaller

Write-Host "[2/3] Cleaning old build artifacts..."
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist) { Remove-Item -Recurse -Force dist }

Write-Host "[3/3] Building GUI executables (one-folder)..."
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name builder_tool `
  --add-data "config;config" `
  builder_gui.py

& $Python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name search_gui `
  --add-data "config;config" `
  search_gui.py

Write-Host "Build completed."
Write-Host "- dist/builder_tool/builder_tool.exe"
Write-Host "- dist/search_gui/search_gui.exe"
