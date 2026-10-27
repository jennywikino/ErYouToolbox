$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$venvPath = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ErYouToolbox\venv'
$python = Join-Path $venvPath 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Local virtual environment not found: $python. Run .\scripts\bootstrap.ps1 from the project directory first."
}
& $python (Join-Path $projectRoot 'scripts\probe_api.py')
exit $LASTEXITCODE
