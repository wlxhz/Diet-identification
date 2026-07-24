$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$appUrl = "http://127.0.0.1:5000"
$pythonCandidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe")
)
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand) { $pythonCandidates += $pythonCommand.Source }
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

function Test-AppReady {
    try {
        $response = Invoke-WebRequest -Uri $appUrl -UseBasicParsing -TimeoutSec 1 -MaximumRedirection 0 -ErrorAction SilentlyContinue
        return $null -ne $response
    } catch {
        if ($_.Exception.Response) { return $true }
        return $false
    }
}

if (Test-AppReady) {
    Start-Process $appUrl
    exit 0
}

if (-not $python) {
    Write-Error "找不到 Python 运行环境，请安装 Python 3 或在项目中创建 .venv"
    exit 1
}

$appFile = Join-Path $projectRoot "app.py"
if (-not (Test-Path -LiteralPath $appFile)) {
    Write-Error "找不到 app.py"
    exit 1
}

$env:PYTHONUTF8 = "1"
$startOptions = @{
    FilePath = $python
    ArgumentList = @($appFile)
    WorkingDirectory = $projectRoot
    WindowStyle = "Hidden"
    PassThru = $true
}
$server = Start-Process @startOptions

for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 250
    if (Test-AppReady) {
        Start-Process $appUrl
        exit 0
    }
    if ($server.HasExited) {
        Write-Error "应用服务异常退出，退出代码：$($server.ExitCode)"
        exit 1
    }
}

Write-Error "等待应用服务启动超时"
exit 1
