$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$port = 11434
$url = "http://127.0.0.1:$port"
$model = "qwen2:7b-instruct"

$candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
    (Join-Path $env:ProgramFiles "Ollama\ollama.exe"),
    (Get-Command ollama -ErrorAction SilentlyContinue).Source
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

$ollama = $candidates | Select-Object -First 1
if (-not $ollama) {
    Write-Host "Ollama was not found."
    Write-Host "Install it first, or put ollama.exe in:"
    Write-Host "  $env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    exit 1
}

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$pidFile = Join-Path $logDir "ollama.pid"
$outLog = Join-Path $logDir "ollama.out.log"
$errLog = Join-Path $logDir "ollama.err.log"

function Test-OllamaApi {
    try {
        $response = Invoke-RestMethod -Uri "$url/api/tags" -TimeoutSec 2
        return $response
    } catch {
        return $null
    }
}

$tags = Test-OllamaApi
if ($tags) {
    Write-Host "Ollama is already running."
} else {
    $env:OLLAMA_HOST = "127.0.0.1:$port"
    $env:OLLAMA_KEEP_ALIVE = "10m"
    $env:OLLAMA_CONTEXT_LENGTH = "8192"
    $env:OLLAMA_NUM_PARALLEL = "1"
    $env:OLLAMA_MAX_LOADED_MODELS = "1"
    $env:OLLAMA_MAX_TRANSFER_STREAMS = "1"
    $process = Start-Process -FilePath $ollama `
        -ArgumentList @("serve") `
        -WorkingDirectory (Split-Path -Parent $ollama) `
        -WindowStyle Hidden `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru
    Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii

    $started = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if ($process.HasExited) { break }
        $tags = Test-OllamaApi
        if ($tags) { $started = $true; break }
    }
    if (-not $started) {
        Write-Host "Ollama failed to start. Last error log:"
        if (Test-Path -LiteralPath $errLog) { Get-Content -LiteralPath $errLog -Tail 20 }
        exit 1
    }
    Write-Host "Ollama started."
}

$tags = Test-OllamaApi
$models = @()
if ($tags -and $tags.models) { $models = @($tags.models) }
$hasModel = $models | Where-Object { $_.name -eq $model -or $_.name -like "$model*" }

Write-Host "URL:   $url"
if ($models.Count -gt 0) {
    Write-Host "Models:"
    foreach ($item in $models) {
        $sizeGb = [math]::Round([double]$item.size / 1GB, 2)
        Write-Host ("  - {0} ({1} GB)" -f $item.name, $sizeGb)
    }
} else {
    Write-Host "Models: none"
}

if (-not $hasModel) {
    Write-Host ""
    Write-Host "Model '$model' is not installed yet. Run:"
    Write-Host "  `"$ollama`" pull $model"
    exit 2
}

Write-Host "Model '$model' is ready."
exit 0
