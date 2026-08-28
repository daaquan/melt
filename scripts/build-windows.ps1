param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $Root $Python

if (-not (Test-Path $PythonPath)) {
    throw "Python environment not found: $PythonPath`nRun: python -m venv .venv"
}

Push-Location $Root
try {
    & $PythonPath -m pip install -e ".[build]"
    & $PythonPath -m PyInstaller `
        --clean `
        --noconfirm `
        --onefile `
        --name "melt-capture" `
        --specpath "$Root\build" `
        --add-data "$Root\locales;locales" `
        "$Root\scripts\melt-capture"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    Copy-Item ".env.example" "dist\.env.example" -Force
    Write-Host "Built: $Root\dist\melt-capture.exe"
} finally {
    Pop-Location
}
