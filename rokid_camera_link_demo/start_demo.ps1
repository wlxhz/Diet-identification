$ErrorActionPreference = "Stop"
$DemoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $DemoRoot
python .\server.py --host 0.0.0.0 --port 9088
