$ErrorActionPreference = "Stop"
$DemoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $DemoRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }

Set-Location -LiteralPath $DemoRoot
& $Python -c "import av, PIL"
if ($LASTEXITCODE -ne 0) {
    throw "缺少视频解码依赖。请运行：$Python -m pip install -r `"$DemoRoot\requirements.txt`""
}

& $Python .\server.py `
    --host 0.0.0.0 `
    --port 9088 `
    --udp-host 0.0.0.0 `
    --udp-port 5000 `
    --recognition-fps 1.5
