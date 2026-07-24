$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot "health_diet_app\.venv\Scripts\python.exe"
$server = Join-Path $projectRoot "rokid_camera_link_demo\server.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Health app Python environment was not found: $python"
}
if (-not (Test-Path -LiteralPath $server)) {
    throw "Rokid backend was not found: $server"
}

$env:PYTHONUTF8 = "1"
Write-Host ""
Write-Host "Starting the Rokid RV101 recognition backend..." -ForegroundColor Green
Write-Host "Connect the phone and PC to the same Wi-Fi."
Write-Host "Enter this PC's IPv4 address and port 9088 in the Android app."
Write-Host ""

& $python $server --host 0.0.0.0 --port 9088
