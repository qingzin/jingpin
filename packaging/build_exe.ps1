param(
  [string]$Python = "python"
)

Write-Host "[1/4] Install project requirements..."
& $Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/4] Install pyinstaller..."
& $Python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/5] Preflight check (Python/PySide6/QtCore)..."
& $Python tools/check_qt_env.py
if ($LASTEXITCODE -ne 0) {
  Write-Host "Preflight failed. Fix PySide6 runtime first, then re-run this script."
  exit $LASTEXITCODE
}

Write-Host "[4/5] Build builder_tool.exe..."
& $Python -m PyInstaller --clean --noconfirm packaging/builder_tool.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[5/5] Build search_gui.exe..."
& $Python -m PyInstaller --clean --noconfirm packaging/search_service.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Done. Output under dist/"
