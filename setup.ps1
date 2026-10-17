$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv/Scripts/python.exe")) {
  python -m venv .venv
}
& .venv/Scripts/python.exe -m pip install -r requirements-dev.txt -c requirements.lock
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm ci --prefix frontend
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run build --prefix frontend
exit $LASTEXITCODE
