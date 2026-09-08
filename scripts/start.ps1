param(
  [switch]$Install,
  [switch]$InstallBrowsers
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Install) {
  python -m pip install -r requirements.txt
  Push-Location frontend
  npm install
  Pop-Location
}

if ($InstallBrowsers) {
  python -m playwright install chromium
}

if (-not (Test-Path 'frontend/node_modules')) {
  Write-Host 'Frontend dependencies are missing. Run .\scripts\start.ps1 -Install once.' -ForegroundColor Yellow
  exit 1
}

$uvicornArgs = @('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000')
if (Test-Path '.env') { $uvicornArgs += @('--env-file', '.env') }
$backend = Start-Process -FilePath 'python' -ArgumentList $uvicornArgs -WorkingDirectory $root -PassThru
try {
  Push-Location frontend
  npm run dev -- --host 127.0.0.1
}
finally {
  Pop-Location
  if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id }
}
