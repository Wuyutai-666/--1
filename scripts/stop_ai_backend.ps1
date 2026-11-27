$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$port = 11434
$logDir = Join-Path $root "logs"
$pidFile = Join-Path $logDir "ollama.pid"

function Stop-OllamaProcess {
    param([int]$ProcessId)
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $info) { return $false }
    if ($info.CommandLine -notmatch 'ollama(\.exe)?"?\s+serve') { return $false }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    return $true
}

$stopped = $false
$stoppedId = $null

if (Test-Path -LiteralPath $pidFile) {
    $raw = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $processId = 0
    if ([int]::TryParse($raw, [ref]$processId) -and $processId -gt 0) {
        if (Stop-OllamaProcess -ProcessId $processId) {
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
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
        if ($info -and $info.Name -eq "ollama.exe") {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
            $stopped = $true
            $stoppedId = $listener.OwningProcess
        }
    }
}

Start-Sleep -Milliseconds 800
if ($stopped) {
    Write-Host "Ollama backend stopped (PID $stoppedId)."
} else {
    Write-Host "Ollama backend is not running."
}
