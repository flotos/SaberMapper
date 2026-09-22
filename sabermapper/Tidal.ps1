$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
& $python (Join-Path $PSScriptRoot 'scripts/tidal_local.py') @args
exit $LASTEXITCODE
