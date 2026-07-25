$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$workspaceRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$pythonCandidates = @(
    (Join-Path $projectRoot "health_diet_app\.venv\Scripts\python.exe"),
    (Join-Path $workspaceRoot "health_diet_app\.venv\Scripts\python.exe")
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$server = Join-Path $projectRoot "rokid_camera_link_demo\server.py"

if (-not $python) {
    throw "Health app Python environment was not found. Checked: $($pythonCandidates -join ', ')"
}
if (-not (Test-Path -LiteralPath $server)) {
    throw "Rokid backend was not found: $server"
}

$env:PYTHONUTF8 = "1"
& $python -c "import av, PIL, cv2, numpy, ultralytics"
if ($LASTEXITCODE -ne 0) {
    throw "Video dependencies are missing. Run: `"$python`" -m pip install -r `"$(Join-Path (Split-Path -Parent $server) 'requirements.txt')`""
}

Write-Host ""
Write-Host "Starting the Rokid RV101 video and recognition backend..." -ForegroundColor Green
Write-Host "HTTP dashboard: http://127.0.0.1:9088/"
Write-Host "Glasses stream: H.264 MPEG-TS over UDP port 5000"
Write-Host "Connect the glasses, phone, and PC to the same Wi-Fi."
Write-Host ""

& $python $server `
    --host 0.0.0.0 `
    --port 9088 `
    --udp-host 0.0.0.0 `
    --udp-port 5000 `
    --preview-fps 10 `
    --recognition-fps 1.5
