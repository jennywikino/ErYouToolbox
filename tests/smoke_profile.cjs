const fs=require('node:fs'),path=require('node:path'),{execFile}=require('node:child_process'),{promisify}=require('node:util')
const execute=promisify(execFile)
function validate(root,out,profile){
  const base=path.resolve(root,'logs/ui_smoke'),run=path.resolve(out),target=path.resolve(profile)
  if(path.dirname(run)!==base||path.basename(target)!=='profile'||path.dirname(target)!==run)throw Error('Profile path outside expected run directory')
  for(const p of [root,path.join(root,'logs'),base,run,target])if(fs.existsSync(p)&&fs.lstatSync(p).isSymbolicLink())throw Error('Reparse/symlink path refused')
  if(fs.realpathSync(run)!==run)throw Error('Run directory resolves elsewhere')
}
async function windowsSafe(profile,pid){
  if(process.platform!=='win32')throw Error('Process/file ownership inspection only implemented on Windows; retained')
  const script=`$ErrorActionPreference='Stop'
$all=@(Get-CimInstance Win32_Process)
$ids=[System.Collections.Generic.HashSet[int]]::new()
[void]$ids.Add([int]$env:ERYOU_SMOKE_PID)
do { $changed=$false; foreach($p in $all){if($ids.Contains([int]$p.ParentProcessId)){if($ids.Add([int]$p.ProcessId)){$changed=$true}}} } while($changed)
$active=@($all | Where-Object { $ids.Contains([int]$_.ProcessId) -or ($_.CommandLine -and $_.CommandLine.Contains($env:ERYOU_SMOKE_PROFILE)) })
if($active.Count){throw 'Browser/profile processes still active; retained'}
foreach($f in Get-ChildItem -LiteralPath $env:ERYOU_SMOKE_PROFILE -Recurse -Force){
 if($f.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Nested reparse point refused'}
 if(-not $f.PSIsContainer){$h=[IO.File]::Open($f.FullName,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None);$h.Dispose()}
}`
  await execute('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,timeout:15000,env:{...process.env,ERYOU_SMOKE_PROFILE:profile,ERYOU_SMOKE_PID:String(pid)}})
}
async function cleanup({root,out,profile,browser,close,inspect=windowsSafe}){
  const result={profile,status:'retained',reason:null}
  try{
    validate(root,out,profile)
    if(close)await close()
    if(!browser||!browser.pid)throw Error('No tracked browser identity; retained')
    const end=Date.now()+10000
    while(browser.exitCode===null&&browser.signalCode===null&&Date.now()<end)await new Promise(r=>setTimeout(r,100))
    if(browser.exitCode===null&&browser.signalCode===null)throw Error('Browser did not exit after graceful close')
    if(fs.existsSync(profile)){
      await inspect(profile,browser.pid)
      validate(root,out,profile)
      fs.rmSync(profile,{recursive:true,force:false,maxRetries:0})
    }
    result.status='removed'
  }catch(e){result.reason=String(e.message||e).slice(0,1200)}
  fs.writeFileSync(path.join(out,'profile_cleanup.json'),JSON.stringify(result,null,2))
  return result
}
module.exports={cleanup,validate}
