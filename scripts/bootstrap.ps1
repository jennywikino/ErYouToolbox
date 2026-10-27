$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$localAppData = [Environment]::GetFolderPath('LocalApplicationData')
$venvPath = Join-Path $localAppData 'ErYouToolbox\venv'

function Test-PythonCommand {
    param([string]$CommandPath, [string[]]$PrefixArguments)
    if (-not $CommandPath -or $CommandPath -match '\\WindowsApps\\') { return $false }
    try {
        & $CommandPath @PrefixArguments --version *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$pythonPath = $null
$pythonPrefix = @()
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    try {
        & $venvPython --version *> $null
        $venvUsable = ($LASTEXITCODE -eq 0)
    } catch {
        $venvUsable = $false
    }
}

if (-not $venvUsable) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $launcherCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonCommand -and (Test-PythonCommand -CommandPath $pythonCommand.Source -PrefixArguments @())) {
        $pythonPath = $pythonCommand.Source
    } elseif ($launcherCommand -and (Test-PythonCommand -CommandPath $launcherCommand.Source -PrefixArguments @('-3'))) {
        $pythonPath = $launcherCommand.Source
        $pythonPrefix = @('-3')
    }

    if (-not $pythonPath) {
        throw 'Python 3 was not found. Install Python 3 or the Python Launcher and make it available on PATH. No software was installed.'
    }
    $venvParent = Split-Path -Parent $venvPath
    New-Item -ItemType Directory -Force -Path $venvParent | Out-Null
    & $pythonPath @pythonPrefix -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed (exit code $LASTEXITCODE)." }
    & $venvPython --version *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment was created but its Python executable is not usable.' }
}

& $venvPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed (exit code $LASTEXITCODE)." }
Write-Host "Virtual environment is ready: $venvPath"
