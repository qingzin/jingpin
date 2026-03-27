param(
  [string]$Python = "python"
)

Write-Host "[1/3] Install pyinstaller..."
& $Python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/3] Build builder_tool.exe..."
& $Python -m PyInstaller --clean --noconfirm packaging/builder_tool.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/3] Build search_service.exe..."
& $Python -m PyInstaller --clean --noconfirm packaging/search_service.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Done. Output under dist/"
