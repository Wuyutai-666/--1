$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$port = 11434
$url = "http://127.0.0.1:$port"
$model = "qwen2:7b-instruct"

$tags = $null
try { $tags = Invoke-RestMethod -Uri "$url/api/tags" -TimeoutSec 3 } catch { $tags = $null }

if (-not $tags) {
    Write-Host "Status: STOPPED"
    Write-Host "Start it by double-clicking the AI start script in the project root."
    exit 1
}

$models = @()
if ($tags.models) { $models = @($tags.models) }
$hasModel = $models | Where-Object { $_.name -eq $model -or $_.name -like "$model*" }

Write-Host "Status: RUNNING"
Write-Host "URL:    $url"
if ($models.Count -gt 0) {
    Write-Host "Models:"
    foreach ($item in $models) {
        $sizeGb = [math]::Round([double]$item.size / 1GB, 2)
        Write-Host ("  - {0} ({1} GB)" -f $item.name, $sizeGb)
    }
} else {
    Write-Host "Models: none"
}
if ($hasModel) {
    Write-Host "Model:  $model READY"
} else {
    Write-Host "Model:  $model MISSING"
}

$webHealth = $null
try { $webHealth = Invoke-RestMethod -Uri "http://127.0.0.1:18080/health" -TimeoutSec 2 } catch { $webHealth = $null }
if ($webHealth -and $webHealth.data.service -eq "meituan-sim") {
    Write-Host "Web:    http://127.0.0.1:18080/ RUNNING"
} else {
    Write-Host "Web:    STOPPED"
}
