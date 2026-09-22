$ErrorActionPreference = 'Stop'
$studioRoot = Split-Path $PSScriptRoot -Parent
$viewerPath = Join-Path $studioRoot 'vendor/arcviewer'
$viewerCommit = 'c776256497b66f7c91a74162cfcd943b0f45ee2e'
if (Test-Path -LiteralPath $viewerPath) {
    $existingCommit = & git -C $viewerPath rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $existingCommit -ne $viewerCommit) { throw 'Existing ArcViewer checkout differs from the pinned build; preserve it and choose a separate SABERMAPPER_ARCVIEWER directory.' }
} else {
    & git clone --depth 1 --branch deploy https://github.com/AllPoland/ArcViewer.git $viewerPath
    if ($LASTEXITCODE -ne 0) { throw 'ArcViewer clone failed.' }
    & git -C $viewerPath fetch --depth 1 origin $viewerCommit
    if ($LASTEXITCODE -ne 0) { throw 'Pinned ArcViewer fetch failed.' }
    & git -C $viewerPath checkout --detach $viewerCommit
    if ($LASTEXITCODE -ne 0) { throw 'Pinned ArcViewer checkout failed.' }
}
Write-Host "Local ArcViewer installed: $viewerPath"
