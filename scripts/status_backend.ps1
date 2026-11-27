$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$port = 18080
$url = "http://127.0.0.1:$port/"

$health = $null
try {
    $health = Invoke-RestMethod -Uri "${url}health" -TimeoutSec 2
} catch {
    $health = $null
}

if ($health -and $health.data.service -eq "meituan-sim") {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    Write-Host "Status: RUNNING"
    Write-Host "URL:    $url"
    if ($listener) { Write-Host "PID:    $($listener.OwningProcess)" }
    Write-Host "DB:     $(Join-Path $root 'data\agent.db')"
    Write-Host "Logs:   $(Join-Path $root 'logs')"
} else {
    Write-Host "Status: STOPPED"
    Write-Host "Start it by double-clicking the start script in the project root."
}
