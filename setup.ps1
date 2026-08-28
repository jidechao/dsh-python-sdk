# Mini Agent 环境准备：安装 Python 依赖并运行体检
# 用法: powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "== install pydantic (the SDK client's only third-party dependency) ==" -ForegroundColor Cyan
& $python -m pip install --quiet "pydantic>=2.12,<3"

Write-Host "== environment doctor ==" -ForegroundColor Cyan
& $python (Join-Path $root "repl.py") --check
exit $LASTEXITCODE
