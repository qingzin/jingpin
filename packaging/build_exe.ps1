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
  --hidden-import shiboken6 `
  --collect-all PySide6 `
  --collect-all shiboken6 `
  --add-data "config;config" `
  builder_gui.py

& $Python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name search_gui `
  --hidden-import shiboken6 `
  --collect-all PySide6 `
  --collect-all shiboken6 `
  --add-data "config;config" `
  search_gui.py

Write-Host "[4/4] Copying VC runtime DLLs (if available)..."
$pyExe = (& $Python -c "import sys; print(sys.executable)").Trim()
$pyDir = Split-Path -Parent $pyExe
$runtimeDlls = @(
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll"
)
$searchDirs = @($pyDir, (Join-Path $pyDir "DLLs"))
foreach ($dll in $runtimeDlls) {
    $src = $null
    foreach ($d in $searchDirs) {
        $candidate = Join-Path $d $dll
        if (Test-Path $candidate) {
            $src = $candidate
            break
        }
    }
    if ($src) {
        Copy-Item -Force $src (Join-Path "dist/builder_tool" $dll)
        Copy-Item -Force $src (Join-Path "dist/search_gui" $dll)
    }
}

Write-Host "Build completed."
Write-Host "- dist/builder_tool/builder_tool.exe"
Write-Host "- dist/search_gui/search_gui.exe"
