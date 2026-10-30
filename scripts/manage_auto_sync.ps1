param(
    [Parameter(Mandatory=$true)][ValidateSet('register','query','disable','delete')][string]$Action,
    [Parameter(Mandatory=$true)][string]$StateDirectory,
    [Parameter(Mandatory=$true)][string]$TaskName,
    [ValidateRange(1,168)][int]$Hours = 6
)
$ErrorActionPreference = 'Stop'
try {
    $bootstrap = Join-Path $StateDirectory 'bootstrap.ps1'
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $bootstrap + '"'
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        if (@($task.Actions).Count -ne 1 -or $task.Actions[0].Execute -ne $powershell -or $task.Actions[0].Arguments -ne $arguments) {
            throw 'Existing task identity does not match this launcher; refusing to modify it.'
        }
    }
    if ($Action -eq 'register') {
        if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf)) { throw 'Missing installed bootstrap.' }
        $taskAction = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval ([TimeSpan]::FromHours($Hours))
        $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromMinutes(90)) -StartWhenAvailable
        Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    } elseif ($Action -eq 'disable' -and $task) {
        Disable-ScheduledTask -TaskName $TaskName | Out-Null
    } elseif ($Action -eq 'delete' -and $task) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $next = $null
    if ($task) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        if ($task.State -ne 'Disabled' -and $info.NextRunTime.Year -gt 2000) { $next = $info.NextRunTime.ToUniversalTime().ToString('o') }
    }
    $result = @{registered=[bool]$task; enabled=([bool]$task -and $task.State -ne 'Disabled'); next_run=$next; state=if($task){[string]$task.State}else{'NotRegistered'}}
    if ($task -and $task.Triggers[0].Repetition.Interval) {
        $result.interval_hours = [System.Xml.XmlConvert]::ToTimeSpan($task.Triggers[0].Repetition.Interval).TotalHours
    }
    $result | ConvertTo-Json -Compress
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
