# Run the web app as the team's shared server: one copy, all data in this machine's runs/.
# Uses the fine-tuned model on the GPU server when it answers, the offline parser otherwise.
#
#   powershell -ExecutionPolicy Bypass -File scripts\host.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\host.ps1 -Offline     # never use the GPU
param(
    [string]$GpuUrl = "http://10.1.25.94:8080/v1",
    [string]$Model = "Qwen3.5-4B-Finetune-NTS-Q8_0",
    [int]$Port = 8000,
    [switch]$Offline
)

Set-Location (Split-Path $PSScriptRoot -Parent)

$env:NTS_HOST = "0.0.0.0"  # reachable from other machines, not only this one
$env:NTS_PORT = "$Port"
$env:NTS_LOCAL_URL = $GpuUrl
$env:NTS_LOCAL_MODEL = $Model

$parser = "offline"
if (-not $Offline) {
    try {
        $models = Invoke-RestMethod -Uri "$GpuUrl/models" -TimeoutSec 5
        if ($models.data.id -contains $Model) { $parser = "local" }
        else { Write-Host "GPU server is up but does not serve $Model; it serves: $($models.data.id -join ', ')" }
    } catch {
        Write-Host "GPU server not reachable at $GpuUrl; starting with the offline parser."
    }
}

Write-Host "Building the front end..."
Push-Location frontend
npm run build --silent
Pop-Location

$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.|172\.)' } | Select-Object -ExpandProperty IPAddress
Write-Host ""
Write-Host "Parser: $parser"
foreach ($ip in $ips) { Write-Host "Team link: http://${ip}:$Port" }
Write-Host ""

uv run nts-web --parser $parser
