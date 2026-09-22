param([int]$Port = 8765, [switch]$NoBrowser, [switch]$Foreground)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$studioPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $studioPython)) { & (Join-Path $PSScriptRoot 'setup.ps1') }
$studioWorkspace = Join-Path $PSScriptRoot 'workspace'
$studioUrl = "http://127.0.0.1:$Port"
if ($Foreground) {
    & $studioPython -m sabermapper serve --workspace $studioWorkspace --port $Port
    exit $LASTEXITCODE
}
$studioRunning = $false
try {
    $studioStatus = Invoke-RestMethod -Uri "$studioUrl/api/status" -TimeoutSec 2
    if ($studioStatus.version -and $studioStatus.workspace -eq $studioWorkspace) { $studioRunning = $true }
    else { throw "Port $Port is used by a different app or workspace. Choose another -Port." }
} catch {
    if ($_.Exception.Message -like 'Port *') { throw }
}
if (-not $studioRunning) {
    $studioLogs = Join-Path $PSScriptRoot 'artifacts'
    New-Item -ItemType Directory -Path $studioLogs -Force | Out-Null
    # Working directory supplies the relative workspace without command-string interpolation.
    $studioProcess = Start-Process -FilePath $studioPython -ArgumentList @('-m', 'sabermapper', 'serve', '--workspace', 'workspace', '--port', "$Port") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $studioLogs 'studio.log') -RedirectStandardError (Join-Path $studioLogs 'studio-errors.log')
    $studioProcess.Id | Set-Content -LiteralPath (Join-Path $studioLogs 'studio.pid')
    for ($studioAttempt = 0; $studioAttempt -lt 40; $studioAttempt++) {
        Start-Sleep -Milliseconds 250
        try { $null = Invoke-RestMethod -Uri "$studioUrl/api/status" -TimeoutSec 1; $studioRunning = $true; break } catch { }
    }
    if (-not $studioRunning) { throw 'Studio did not start. Inspect artifacts/studio-errors.log.' }
}
Write-Host "SaberMapper Studio: $studioUrl"
if (-not $NoBrowser) { Start-Process $studioUrl }
