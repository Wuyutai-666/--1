$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$port = 18080
$logDir = Join-Path $root "logs"
$pidFile = Join-Path $logDir "backend.pid"

function Stop-FanDianProcess {
    param([int]$ProcessId)
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $info) { return $false }
    if ($info.CommandLine -notmatch 'meituan_sim\.server') { return $false }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    return $true
}

$stopped = $false
$stoppedId = $null

if (Test-Path -LiteralPath $pidFile) {
    $raw = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $processId = 0
    if ([int]::TryParse($raw, [ref]$processId) -and $processId -gt 0) {
        if (Stop-FanDianProcess -ProcessId $processId) {
            $stopped = $true
            $stoppedId = $processId
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

if (-not $stopped) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        if (Stop-FanDianProcess -ProcessId $listener.OwningProcess) {
            $stopped = $true
            $stoppedId = $listener.OwningProcess
        }
    }
}

if ($stopped) {
    Write-Host "FanDian backend stopped (PID $stoppedId)."
} else {
    Write-Host "FanDian backend is not running."
}
