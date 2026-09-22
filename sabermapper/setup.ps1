param([switch]$Development)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or later is required. Install Python and rerun setup.ps1.' }
}
if ($Development) {
    & '.venv/Scripts/python.exe' -m pip install -e '.[dev]'
} else {
    & '.venv/Scripts/python.exe' -m pip install -e .
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. See the pip output above.' }
Write-Host 'SaberMapper is installed. Run Start-SaberMapper.ps1 to open the studio.'
