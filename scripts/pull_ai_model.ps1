$ErrorActionPreference = "Stop"

$model = "qwen2:7b-instruct"
$candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
    (Join-Path $env:ProgramFiles "Ollama\ollama.exe"),
    (Get-Command ollama -ErrorAction SilentlyContinue).Source
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

$ollama = $candidates | Select-Object -First 1
if (-not $ollama) {
    Write-Host "Ollama was not found. Install Ollama first."
    exit 1
}

$env:OLLAMA_HOST = "127.0.0.1:11434"
& (Join-Path $PSScriptRoot "start_ai_backend.ps1")
$startCode = $LASTEXITCODE
if ($startCode -eq 1) { exit 1 }

Write-Host ""
Write-Host "Pulling model: $model"
Write-Host "This downloads about 4.1 GB and may take a while."
& $ollama pull $model
$pullCode = $LASTEXITCODE
if ($pullCode -ne 0) {
    Write-Host "Model pull failed (exit code $pullCode)."
    exit $pullCode
}

Write-Host ""
Write-Host "Model is ready:"
& $ollama list
