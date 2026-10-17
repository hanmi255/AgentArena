$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& .venv/Scripts/python.exe -m arena.main
exit $LASTEXITCODE
