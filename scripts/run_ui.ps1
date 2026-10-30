$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ErYouToolbox\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Error "Project virtual environment not found: $venvPython. Run scripts\bootstrap.ps1 first."
    exit 1
}
& $venvPython -c 'import streamlit' *> $null
if ($LASTEXITCODE -ne 0) {
    $uiRequirements = Join-Path $projectRoot 'requirements-ui.txt'
    Write-Error "Streamlit is not installed. Install UI dependencies with: $venvPython -m pip install -r $uiRequirements"
    exit 1
}
& $venvPython -m streamlit run (Join-Path $projectRoot 'scripts\ui_app.py') --server.address 127.0.0.1 --server.port 8501 --server.headless true
exit $LASTEXITCODE
