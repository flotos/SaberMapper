$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'sabermapper/Tidal.ps1') @args
exit $LASTEXITCODE
