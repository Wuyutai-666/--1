$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$port = 18080
$url = "http://127.0.0.1:$port/"

Set-Location -LiteralPath $root

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-Content -LiteralPath $Path | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $name = $matches[1]
            $value = $matches[2]
            if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

Import-DotEnv (Join-Path $root ".env")
$env:PYTHONUTF8 = "1"

$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($existing) {
    try {
        $health = Invoke-RestMethod -Uri "${url}health" -TimeoutSec 2
        if ($health.data.service -eq "meituan-sim") {
            Write-Host "FanDian backend is already running."
            Write-Host "URL:  $url"
            Write-Host "PID:  $($existing.OwningProcess)"
            exit 0
        }
    } catch {
        # Port is used by another program, reported below.
    }
    Write-Host "Port $port is already used by another program (PID $($existing.OwningProcess))."
    Write-Host "Close it, or start with a different port:"
    Write-Host "  python -m meituan_sim.server --port 18081"
    exit 1
}

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Host "Python was not found in PATH. Install Python 3.12+ and try again."
    exit 1
}

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$outLog = Join-Path $logDir "backend.out.log"
$errLog = Join-Path $logDir "backend.err.log"
$pidFile = Join-Path $logDir "backend.pid"

$process = Start-Process -FilePath $python `
    -ArgumentList @("-m", "meituan_sim.server", "--host", "127.0.0.1", "--port", "$port") `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii

$started = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 400
    if ($process.HasExited) { break }
    try {
        $health = Invoke-RestMethod -Uri "${url}health" -TimeoutSec 2
        if ($health.data.service -eq "meituan-sim") {
            $started = $true
            break
        }
    } catch {
        # Server is still starting.
    }
}

if (-not $started) {
    Write-Host "Backend failed to start. Last error log:"
    if (Test-Path -LiteralPath $errLog) {
        Get-Content -LiteralPath $errLog -Tail 20
    }
    exit 1
}

Write-Host "FanDian backend started."
Write-Host "URL:  $url"
Write-Host "PID:  $($process.Id)"
Write-Host "Logs: $logDir"
