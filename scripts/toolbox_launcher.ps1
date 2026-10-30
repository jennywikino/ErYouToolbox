param([Parameter(Mandatory = $true)][ValidateSet('Start','Stop')][string]$Action)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')
$LocalData = $env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($LocalData)) { $LocalData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData) }
$sha = [Security.Cryptography.SHA256]::Create()
try { $rootHash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($ProjectRoot.ToLowerInvariant()))).Replace('-','').Substring(0,16) }
finally { $sha.Dispose() }
$StateDirectory = Join-Path $LocalData (Join-Path 'ErYouToolbox\launcher' $rootHash)
$StatePath = Join-Path $StateDirectory 'services.json'
$LogPath = Join-Path $StateDirectory 'launcher.log'
$PythonPath = Join-Path $LocalData 'ErYouToolbox\venv\Scripts\python.exe'
$ApiPath = Join-Path $ProjectRoot 'scripts\react_api.py'
$FrontendPath = Join-Path $ProjectRoot 'frontend'
$ApiPort = 8766
$WebPort = 5173
$Mutex = $null
$MutexOwned = $false
$ExitCode = 0
$script:FailureStage = 'initialization'
$script:LastIdentityError = ''

function Write-Log([string]$Message,[string]$Level='INFO') {
    Write-Host $Message
    try {
        if (-not (Test-Path -LiteralPath $StateDirectory)) { New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null }
        Add-Content -LiteralPath $LogPath -Value ('{0} [{1}] {2}' -f [DateTime]::UtcNow.ToString('o'),$Level,$Message) -Encoding UTF8
    } catch { Write-Host ('Could not append launcher log: ' + $_.Exception.Message) }
}

function Write-IdentityLog([string]$Label,$Identity) {
    if (-not $Identity) { Write-Log ("{0}: identity unavailable. {1}" -f $Label,$script:LastIdentityError) 'WARN'; return }
    Write-Log ("{0}: PID={1}; CreatedUtc={2}; Executable={3}; ParentPID={4}; CommandLine={5}" -f $Label,$Identity.Pid,([DateTime]::new([long]$Identity.StartedUtcTicks,[DateTimeKind]::Utc).ToString('o')),$Identity.Executable,$Identity.ParentPid,$Identity.CommandLine)
}

function ConvertTo-CimUtcDateTime($Value) {
    if ($Value -is [DateTime]) { return $Value.ToUniversalTime() }
    return [Management.ManagementDateTimeConverter]::ToDateTime([string]$Value).ToUniversalTime()
}

function Get-ProcessIdentity([int]$ProcessId) {
    try {
        $p = Get-Process -Id $ProcessId -ErrorAction Stop
        $w = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
        if (-not $w) { throw 'Win32_Process returned no matching process.' }
        if (-not $w.ExecutablePath) { throw 'ExecutablePath is unavailable (access denied or process exited during inspection).' }
        if (-not $w.CommandLine) { throw 'CommandLine is unavailable (access denied or process exited during inspection).' }
        $started=ConvertTo-CimUtcDateTime $w.CreationDate
        $script:LastIdentityError = ''
        [pscustomobject]@{ Pid=[int]$ProcessId; StartedUtcTicks=[long]$started.Ticks
            Executable=[IO.Path]::GetFullPath([string]$w.ExecutablePath); CommandLine=[string]$w.CommandLine; ParentPid=[int]$w.ParentProcessId }
    } catch { $script:LastIdentityError=('PID {0}: {1}' -f $ProcessId,$_.Exception.Message); return $null }
}

function Test-Identity($Expected,[string]$Service) {
    if (-not $Expected) { return $false }
    $actual = Get-ProcessIdentity ([int]$Expected.Pid)
    if (-not $actual -or $actual.StartedUtcTicks -ne [long]$Expected.StartedUtcTicks) { return $false }
    if (-not [string]::Equals($actual.Executable,[string]$Expected.Executable,[StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($actual.CommandLine,[string]$Expected.CommandLine,[StringComparison]::OrdinalIgnoreCase)) { return $false }
    if ($Service -eq 'python-api') { return $actual.CommandLine.IndexOf($ApiPath,[StringComparison]::OrdinalIgnoreCase) -ge 0 }
    if ($Service -eq 'pnpm-launcher') {
        return ($actual.Executable -match '\\cmd\.exe$' -and
            $actual.CommandLine.IndexOf([string]$Expected.PnpmPath,[StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $actual.CommandLine -match '(?i)\bdev\b')
    }
    if ($Service -eq 'vite-server') {
        $valid=($actual.Executable -match '\\node\.exe$' -and
            $actual.CommandLine -match '(?i)vite' -and $actual.CommandLine.IndexOf('127.0.0.1',[StringComparison]::OrdinalIgnoreCase) -ge 0)
        if ($valid -and $Expected.PnpmRootPid -and $Expected.PnpmRootTicks) {
            return Test-DescendantOf $actual ([int]$Expected.PnpmRootPid) ([long]$Expected.PnpmRootTicks)
        }
        return $valid
    }
    return $false
}

function Test-DescendantOf($Identity,$RootPid,[long]$RootTicks) {
    try {
        $all=@(Get-CimInstance Win32_Process -ErrorAction Stop)
        $byId=@{}
        foreach ($p in $all) { $byId[[string]$p.ProcessId]=$p }
        $current=$Identity
        for ($i=0; $i -lt 32; $i++) {
            if ($current.ParentPid -eq [int]$RootPid) {
                $parent=$byId[[string]$RootPid]
                if (-not $parent) { return $false }
                $ticks=(ConvertTo-CimUtcDateTime $parent.CreationDate).Ticks
                return ([Math]::Abs($ticks-$RootTicks) -le [TimeSpan]::FromSeconds(2).Ticks -and $current.StartedUtcTicks -ge ($RootTicks-[TimeSpan]::FromSeconds(2).Ticks))
            }
            $parent=$byId[[string]$current.ParentPid]
            if (-not $parent) { return $false }
            $ticks=(ConvertTo-CimUtcDateTime $parent.CreationDate).Ticks
            if ($current.StartedUtcTicks -lt $ticks) { return $false }
            $current=[pscustomobject]@{ParentPid=[int]$parent.ParentProcessId;StartedUtcTicks=$ticks}
        }
    } catch { return $false }
    return $false
}

function Test-StartedByProcess($ServiceIdentity,$LaunchIdentity,[int]$WindowSeconds=45) {
    if (-not $ServiceIdentity -or -not $LaunchIdentity) { return $false }
    if ($ServiceIdentity.Pid -eq $LaunchIdentity.Pid) {
        return ($ServiceIdentity.StartedUtcTicks -eq $LaunchIdentity.StartedUtcTicks -and
            [string]::Equals($ServiceIdentity.Executable,$LaunchIdentity.Executable,[StringComparison]::OrdinalIgnoreCase) -and
            [string]::Equals($ServiceIdentity.CommandLine,$LaunchIdentity.CommandLine,[StringComparison]::OrdinalIgnoreCase))
    }
    $elapsed=[long]$ServiceIdentity.StartedUtcTicks-[long]$LaunchIdentity.StartedUtcTicks
    if ($elapsed -lt 0 -or $elapsed -gt [TimeSpan]::FromSeconds($WindowSeconds).Ticks) { return $false }
    if ($ServiceIdentity.ParentPid -eq $LaunchIdentity.Pid) { return $true }
    return Test-DescendantOf $ServiceIdentity ([int]$LaunchIdentity.Pid) ([long]$LaunchIdentity.StartedUtcTicks)
}

function Get-PortOwners([int]$Port) {
    $sockets = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    return @($sockets | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { [int]$_ })
}

function Write-State($State) {
    $temp = $StatePath + '.tmp'
    $State | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $StatePath -Force
}

function Read-State {
    if (-not (Test-Path -LiteralPath $StatePath)) { return $null }
    try {
        $s = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($s.ProjectRoot -ne $ProjectRoot -or -not $s.Services) { throw 'Project identity mismatch.' }
        return $s
    } catch { throw ('Cannot validate local service state: ' + $_.Exception.Message) }
}

function Save-ProcessRecord([string]$Name,$Identity,$State,[hashtable]$Extra=@{}) {
    $entry = @{ Service=$Name; Pid=$Identity.Pid; StartedUtcTicks=$Identity.StartedUtcTicks
        Executable=$Identity.Executable; CommandLine=$Identity.CommandLine; ParentPid=$Identity.ParentPid
        ProjectRoot=$ProjectRoot; StartedAtUtc=[DateTime]::UtcNow.ToString('o') }
    foreach ($key in $Extra.Keys) { $entry[$key]=$Extra[$key] }
    $State.Services[$Name]=$entry
    Write-State $State
}

function Wait-ServiceReady([int]$Port,[string]$Url,[string]$Service,[int]$Timeout=30,$ExpectedRoot=$null) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Timeout)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                $owners = @(Get-PortOwners $Port)
                if ($owners.Count -ne 1) { throw ('Cannot identify listener on port ' + $Port) }
                Write-Log ('Readiness HTTP {0} for {1}; port {2} owner PID {3}.' -f $response.StatusCode,$Service,$Port,$owners[0])
                $identity = Get-ProcessIdentity $owners[0]
                if (-not $identity) {
                    Write-Log ('Listener identity inspection failed: ' + $script:LastIdentityError) 'ERROR'
                    throw ('Cannot verify listener identity on port {0}: {1}' -f $Port,$script:LastIdentityError)
                }
                Write-IdentityLog ('Port ' + $Port + ' listener') $identity
                $ownersAfter = @(Get-PortOwners $Port)
                if ($ownersAfter.Count -ne 1 -or $ownersAfter[0] -ne $owners[0]) {
                    Write-Log ('Port {0} owner changed during readiness check ({1} -> {2}).' -f $Port,$owners[0],($ownersAfter -join ',')) 'WARN'
                    Start-Sleep -Milliseconds 200
                    continue
                }
                if (-not $identity -or -not (Test-Identity $identity $Service)) {
                    throw ('Port {0} belongs to an unrecognized PID {1}; it was left running.' -f $Port,$owners[0])
                }
                if ($Service -eq 'vite-server' -and $ExpectedRoot -and
                    -not (Test-DescendantOf $identity ([int]$ExpectedRoot.Pid) ([long]$ExpectedRoot.StartedUtcTicks))) {
                    throw ('Port {0} is not served by this pnpm process tree; it was left running.' -f $Port)
                }
                return $identity
            }
        } catch {
            if ($_.Exception.Message -match 'unrecognized PID|Cannot identify listener|Cannot verify listener identity') { throw }
        }
        Start-Sleep -Milliseconds 400
    }
    throw ('Service on port {0} did not become ready within {1}s. Logs: {2}' -f $Port,$Timeout,$StateDirectory)
}

function Get-ProcessTree([int]$RootPid,[long]$RootTicks) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $children = @{}
    foreach ($p in $all) {
        $k=[string]$p.ParentProcessId
        if (-not $children.ContainsKey($k)) { $children[$k]=New-Object System.Collections.ArrayList }
        [void]$children[$k].Add($p)
    }
    $rootDate=[DateTime]::new($RootTicks,[DateTimeKind]::Utc)
    $queue=New-Object System.Collections.Queue
    $queue.Enqueue(@{Pid=$RootPid;Depth=0;Created=$rootDate})
    $seen=@{}
    $tree=New-Object System.Collections.ArrayList
    while ($queue.Count -gt 0) {
        $parent=$queue.Dequeue()
        if (-not $children.ContainsKey([string]$parent.Pid)) { continue }
        foreach ($p in $children[[string]$parent.Pid]) {
            if ($seen.ContainsKey([string]$p.ProcessId)) { continue }
            $created=ConvertTo-CimUtcDateTime $p.CreationDate
            if ($created -lt $parent.Created) { continue }
            $seen[[string]$p.ProcessId]=$true
            $record=[pscustomobject]@{Pid=[int]$p.ProcessId;ParentPid=[int]$p.ParentProcessId
                Depth=[int]($parent.Depth+1);CreatedUtcTicks=[long]$created.Ticks
                Executable=[string]$p.ExecutablePath;CommandLine=[string]$p.CommandLine}
            [void]$tree.Add($record)
            $queue.Enqueue(@{Pid=$record.Pid;Depth=$record.Depth;Created=$created})
        }
    }
    return @($tree | Sort-Object Depth -Descending)
}

function Stop-ExactProcess($Record) {
    $current=Get-ProcessIdentity ([int]$Record.Pid)
    if (-not $current) { return 'already exited' }
    if ($current.StartedUtcTicks -ne [long]$Record.StartedUtcTicks -or
        -not [string]::Equals($current.Executable,[string]$Record.Executable,[StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($current.CommandLine,[string]$Record.CommandLine,[StringComparison]::OrdinalIgnoreCase)) {
        return 'PID identity changed; left untouched'
    }
    Stop-Process -Id ([int]$Record.Pid) -ErrorAction Stop
    return 'stopped'
}

function Stop-Tree($RootRecord,$RecordedLeaf=$null) {
    $tree=@(Get-ProcessTree ([int]$RootRecord.Pid) ([long]$RootRecord.StartedUtcTicks))
    if ($RecordedLeaf) {
        $leaf=@($tree | Where-Object { $_.Pid -eq [int]$RecordedLeaf.Pid })
        if ($leaf.Count -ne 1 -or $leaf[0].CreatedUtcTicks -ne [long]$RecordedLeaf.StartedUtcTicks -or
            -not [string]::Equals($leaf[0].Executable,[string]$RecordedLeaf.Executable,[StringComparison]::OrdinalIgnoreCase) -or
            -not [string]::Equals($leaf[0].CommandLine,[string]$RecordedLeaf.CommandLine,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'Could not confirm Vite belongs to the recorded pnpm process; React processes were left running.'
        }
    }
    foreach ($child in $tree) {
        $current=Get-ProcessIdentity $child.Pid
        if (-not $current) { continue }
        if ($current.StartedUtcTicks -ne $child.CreatedUtcTicks -or
            -not [string]::Equals($current.Executable,$child.Executable,[StringComparison]::OrdinalIgnoreCase) -or
            -not [string]::Equals($current.CommandLine,$child.CommandLine,[StringComparison]::OrdinalIgnoreCase)) {
            throw ('Child PID {0} changed identity; left the process tree untouched.' -f $child.Pid)
        }
        Stop-Process -Id $child.Pid -ErrorAction Stop
    }
    $result=Stop-ExactProcess $RootRecord
    if ($result -eq 'PID identity changed; left untouched') { throw ('Root PID {0} changed identity and was left untouched.' -f $RootRecord.Pid) }
}

function Stop-RecordedServices($State) {
    $issues=New-Object System.Collections.Generic.List[string]
    $api=$State.Services.'python-api'
    $react=$State.Services.'pnpm-launcher'
    $vite=$State.Services.'vite-server'
    if ($react -and (Test-Identity $react 'pnpm-launcher')) {
        try { Stop-Tree $react $vite } catch { $issues.Add($_.Exception.Message) }
    } elseif ($vite -and (Test-Identity $vite 'vite-server')) {
        $owners=@(Get-PortOwners $WebPort)
        if ($owners.Count -eq 1 -and $owners[0] -eq [int]$vite.Pid) {
            try { Stop-Tree $vite } catch { $issues.Add($_.Exception.Message) }
        } elseif ($owners.Count -gt 0) { $issues.Add('Port 5173 belongs to another process and was left untouched.') }
    }
    if ($api) {
        if (Test-Identity $api 'python-api') {
            $result=Stop-ExactProcess $api
            if ($result -ne 'stopped' -and $result -ne 'already exited') { $issues.Add('API ' + $result) }
            if ($api.LaunchPid -and [int]$api.LaunchPid -ne [int]$api.Pid) {
                $launch=[pscustomobject]@{Pid=[int]$api.LaunchPid;StartedUtcTicks=[long]$api.LaunchStartedUtcTicks
                    Executable=[string]$api.LaunchExecutable;CommandLine=[string]$api.LaunchCommandLine}
                if (Test-Identity $launch 'python-api') {
                    $launchResult=Stop-ExactProcess $launch
                    if ($launchResult -ne 'stopped' -and $launchResult -ne 'already exited') { $issues.Add('Python launch process ' + $launchResult) }
                }
            }
        } elseif ((Get-PortOwners $ApiPort).Count -gt 0) {
            $issues.Add('API identity changed while 8766 is active; it was left untouched.')
        }
    }
    if ($issues.Count -gt 0) {
        Write-Log ($issues -join ' ') 'WARN'
        throw 'Some processes could not be safely confirmed. The state file was retained.'
    }
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    Write-Log 'Stopped the recorded services. Browser windows were not closed.'
}

function Start-Toolbox {
    $script:FailureStage='preflight'
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw ('Python virtual environment missing at {0}. Run scripts\bootstrap.ps1.' -f $PythonPath)
    }
    $probe=& $PythonPath -c 'import sys; print(sys.executable)' 2>&1
    if ($LASTEXITCODE -ne 0 -or [string]$probe -notmatch '(?i)ErYouToolbox[\\/]venv[\\/]Scripts[\\/]python\.exe$') {
        throw ('Local Python virtual environment is not usable: ' + $PythonPath)
    }
    if (-not (Test-Path -LiteralPath $ApiPath)) { throw ('Python API file is missing: ' + $ApiPath) }
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendPath 'package.json')) -or
        -not (Test-Path -LiteralPath (Join-Path $FrontendPath 'node_modules\vite\bin\vite.js'))) {
        throw ('React dependencies are missing. Run pnpm.cmd install in ' + $FrontendPath)
    }
    $pnpm=Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    if (-not $pnpm) { throw 'pnpm.cmd was not found on PATH. Install Node.js and pnpm, then reopen PowerShell.' }
    $node=Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) { throw 'node.exe was not found on PATH. Install Node.js and pnpm, then reopen PowerShell.' }
    $pnpmPath=[IO.Path]::GetFullPath($pnpm.Source)
    $nodePath=[IO.Path]::GetFullPath($node.Source)
    $viteConfig=Get-Content -LiteralPath (Join-Path $FrontendPath 'vite.config.ts') -Raw
    if ($viteConfig -notmatch "host:\s*'127\.0\.0\.1'" -or $viteConfig -notmatch 'port:\s*5173' -or $viteConfig -notmatch 'strictPort:\s*true') {
        throw 'Vite must use 127.0.0.1:5173 with strictPort enabled.'
    }
    $old=Read-State
    if ($old) {
        $apiValid=Test-Identity $old.Services.'python-api' 'python-api'
        $launcherValid=Test-Identity $old.Services.'pnpm-launcher' 'pnpm-launcher'
        $viteValid=Test-Identity $old.Services.'vite-server' 'vite-server'
        $apiOwners=@(Get-PortOwners $ApiPort)
        $webOwners=@(Get-PortOwners $WebPort)
        if ($apiValid -and $launcherValid -and $viteValid -and $apiOwners.Count -eq 1 -and $apiOwners[0] -eq [int]$old.Services.'python-api'.Pid -and
            $webOwners.Count -eq 1 -and $webOwners[0] -eq [int]$old.Services.'vite-server'.Pid) {
            Write-Log 'ErYouToolbox is already running. No duplicate services were started.'
            return
        }
        if ($apiValid -or $viteValid -or (Test-Identity $old.Services.'pnpm-launcher' 'pnpm-launcher')) {
            Stop-RecordedServices $old
        } else {
            Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
            Write-Log 'Removed expired local service state.'
        }
    }
    foreach ($port in @($ApiPort,$WebPort)) {
        $owners=@(Get-PortOwners $port)
        if ($owners.Count -gt 0) { throw ('Port {0} is occupied by PID {1}. Close it manually before starting.' -f $port,($owners -join ', ')) }
    }
    $state=[ordered]@{ProjectRoot=$ProjectRoot;StartedAtUtc=[DateTime]::UtcNow.ToString('o');Services=@{}}
    Write-State $state
    $apiOut=Join-Path $StateDirectory 'python-api.out.log'
    $apiErr=Join-Path $StateDirectory 'python-api.err.log'
    $script:FailureStage='python-start'
    Write-Log ('Starting Python API with executable {0}; script {1}; port {2}.' -f $PythonPath,$ApiPath,$ApiPort)
    $apiProcess=Start-Process -FilePath $PythonPath -ArgumentList @('-u',('"{0}"' -f $ApiPath)) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr
    $apiLaunchPid=[int]$apiProcess.Id
    Write-Log ('Start-Process returned Python launch PID {0}.' -f $apiLaunchPid)
    $apiIdentity=Get-ProcessIdentity $apiProcess.Id
    if (-not $apiIdentity) {
        Write-Log ('Python launch identity unavailable: ' + $script:LastIdentityError) 'ERROR'
        throw 'Could not verify the Python process returned by Start-Process.'
    }
    Write-IdentityLog 'Python Start-Process identity' $apiIdentity
    if ($apiIdentity.CommandLine.IndexOf($ApiPath,[StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Write-Log 'Start-Process PID command line does not identify this project API script.' 'ERROR'
        throw 'The process returned by Start-Process is not verifiably running this project API.'
    }
    Save-ProcessRecord 'python-api' $apiIdentity $state
    $script:FailureStage='python-readiness'
    $apiReady=Wait-ServiceReady $ApiPort ('http://127.0.0.1:{0}/api/games' -f $ApiPort) 'python-api'
    Write-IdentityLog 'Verified Python API listener' $apiReady
    if (-not (Test-StartedByProcess $apiReady $apiIdentity)) {
        Write-Log ('Python API listener PID {0} could not be linked to Start-Process PID {1}; listener was left untouched.' -f $apiReady.Pid,$apiIdentity.Pid) 'ERROR'
        throw 'Python API returned HTTP success, but listener process ownership could not be verified.'
    }
    Write-Log ('Verified Python API launch relation: launch PID {0}, listener PID {1}, listener parent PID {2}.' -f $apiIdentity.Pid,$apiReady.Pid,$apiReady.ParentPid)
    Save-ProcessRecord 'python-api' $apiReady $state @{LaunchPid=$apiIdentity.Pid;LaunchStartedUtcTicks=$apiIdentity.StartedUtcTicks;LaunchExecutable=$apiIdentity.Executable;LaunchCommandLine=$apiIdentity.CommandLine}
    Write-Log ('Python API ready at 127.0.0.1:{0}; launch PID {1}; listener PID {2}.' -f $ApiPort,$apiIdentity.Pid,$apiReady.Pid)
    $reactOut=Join-Path $StateDirectory 'react-vite.out.log'
    $reactErr=Join-Path $StateDirectory 'react-vite.err.log'
    $cmd='/d /s /c ""{0}" dev"' -f $pnpmPath
    $script:FailureStage='react-start'
    Write-Log ('Starting React with command {0}; working directory {1}.' -f $cmd,$FrontendPath)
    $reactProcess=Start-Process -FilePath $env:ComSpec -ArgumentList $cmd -WorkingDirectory $FrontendPath -WindowStyle Hidden -PassThru -RedirectStandardOutput $reactOut -RedirectStandardError $reactErr
    Write-Log ('Start-Process returned React command-shell PID {0}.' -f $reactProcess.Id)
    $reactIdentity=Get-ProcessIdentity $reactProcess.Id
    if (-not $reactIdentity) {
        Write-Log ('React command-shell identity unavailable: ' + $script:LastIdentityError) 'ERROR'
        throw 'Could not verify the React command shell returned by Start-Process.'
    }
    Write-IdentityLog 'React command-shell identity' $reactIdentity
    Save-ProcessRecord 'pnpm-launcher' $reactIdentity $state @{PnpmPath=$pnpmPath;NodePath=$nodePath}
    $script:FailureStage='react-readiness'
    $viteIdentity=Wait-ServiceReady $WebPort ('http://127.0.0.1:{0}/' -f $WebPort) 'vite-server' 30 $reactIdentity
    Save-ProcessRecord 'vite-server' $viteIdentity $state @{PnpmPath=$pnpmPath;NodePath=$nodePath;PnpmRootPid=$reactIdentity.Pid;PnpmRootTicks=$reactIdentity.StartedUtcTicks}
    Write-IdentityLog 'Verified Vite listener' $viteIdentity
    Write-Log ('React server ready at 127.0.0.1:{0} (PID {1}).' -f $WebPort,$viteIdentity.Pid)
    $script:FailureStage='open-browser'
    Start-Process -FilePath ('http://127.0.0.1:{0}/' -f $WebPort) | Out-Null
    Write-Log ('Opened http://127.0.0.1:{0}/' -f $WebPort)
}

try {
    New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
    $Mutex=New-Object System.Threading.Mutex($false,'Local\ErYouToolboxLauncher')
    $MutexOwned=$Mutex.WaitOne(0)
    if (-not $MutexOwned) { throw 'Another ErYouToolbox start/stop operation is in progress.' }
    if (-not (Get-ProcessIdentity $PID)) { throw 'Windows process identity inspection is unavailable; no services were started or stopped.' }
    if ($Action -eq 'Start') { Start-Toolbox }
    else {
        $state=Read-State
        if (-not $state) { Write-Log 'No active service state exists for this project.' }
        else { Stop-RecordedServices $state }
    }
} catch {
    Write-Log ('Failure stage: ' + $script:FailureStage) 'ERROR'
    Write-Log $_.Exception.Message 'ERROR'
    if ($Action -eq 'Start') {
        try { $failed=Read-State; if ($failed) { Stop-RecordedServices $failed } }
        catch { Write-Log ('Startup cleanup: ' + $_.Exception.Message) 'WARN' }
        Write-Log ('Logs: ' + $StateDirectory)
    }
    $ExitCode=1
} finally {
    if ($Mutex -and $MutexOwned) { try { $Mutex.ReleaseMutex() } catch {} }
    if ($Mutex) { $Mutex.Dispose() }
}
exit $ExitCode
