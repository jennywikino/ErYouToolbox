param([string]$LocatorPath = (Join-Path $PSScriptRoot 'locator.json'))
$ErrorActionPreference = 'Stop'
try {
    $locator = Get-Content -LiteralPath $LocatorPath -Raw | ConvertFrom-Json
    if ($locator.format -ne 'eryoutoolbox-auto-locator-v1' -or
        [IO.Path]::IsPathRooted($locator.relative_root) -or
        $locator.relative_root -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Invalid project locator.' }
    $matchesFound = @()
    foreach ($drive in [IO.DriveInfo]::GetDrives()) {
        if (-not $drive.IsReady -or $drive.DriveType -eq 'Network') { continue }
        $candidate = Join-Path $drive.RootDirectory.FullName $locator.relative_root
        $marker = Join-Path $candidate 'config\project_identity.json'
        if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { continue }
        $identity = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        if ($identity.project_id -eq $locator.project_id -and
            (Test-Path -LiteralPath (Join-Path $candidate 'scripts\auto_sync.py') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $candidate 'data\eryoutoolbox.db') -PathType Leaf)) {
            $matchesFound += $candidate
        }
    }
    if ($matchesFound.Count -ne 1) { throw "Expected exactly one existing project; found $($matchesFound.Count). No database was created." }
    $python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Project Python venv is missing on this computer.' }
    $script = Join-Path $matchesFound[0] 'scripts\auto_sync.py'
    & $python $script >> (Join-Path $PSScriptRoot 'scheduled.out.log') 2>> (Join-Path $PSScriptRoot 'scheduled.err.log')
    exit $LASTEXITCODE
} catch {
    $_.Exception.Message | Out-File -LiteralPath (Join-Path $PSScriptRoot 'scheduled.err.log') -Append -Encoding utf8
    exit 1
}
