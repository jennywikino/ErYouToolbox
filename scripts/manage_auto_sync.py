"""Explicit device-local Task Scheduler administration. Never runs at API startup."""
import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
import time
from auto_sync import ROOT, AutoSync, atomic_json, identity, runtime_dir, validate_root

def locator(root):
    path=PureWindowsPath(str(root))
    if not path.drive or not path.is_absolute():raise ValueError('Windows drive path required for registration')
    return {'format':'eryoutoolbox-auto-locator-v1','project_id':identity(root),'relative_root':str(path.relative_to(path.anchor))}

def manage(action,root=ROOT,state_dir=None):
    if os.name!='nt':raise ValueError('Windows Task Scheduler is required')
    directory=Path(state_dir) if state_dir else runtime_dir(root)
    auto=AutoSync(root,state_dir=directory);settings=auto.settings()
    if action=='register':
        validate_root(root)
        directory.mkdir(parents=True,exist_ok=True)
        atomic_json(directory/'locator.json',locator(root))
        shutil.copyfile(Path(root)/'scripts/auto_sync_bootstrap.ps1',directory/'bootstrap.ps1')
    executable=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    completed=subprocess.run([str(executable),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(root)/'scripts/manage_auto_sync.ps1'),
                              '-Action',action,'-StateDirectory',str(directory),'-TaskName','ErYouToolbox-AutoSync-'+identity(root)[:8],'-Hours',str(settings['interval_hours'])],
                             capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if completed.returncode:raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or 'Task operation failed')
    result=json.loads(completed.stdout.strip().lstrip('\ufeff'))
    if action!='query':atomic_json(directory/'registration.json',result)
    return result

_cache={}
def task_status(root,directory):
    key=str(directory);cached=_cache.get(key)
    if cached and time.monotonic()-cached[0]<30:return cached[1]
    if not (Path(directory)/'registration.json').exists():return {'registered':False,'enabled':False}
    try:result=manage('query',root,directory)
    except (OSError,RuntimeError,ValueError,subprocess.SubprocessError) as exc:result={'registered':None,'error':str(exc)}
    _cache[key]=(time.monotonic(),result);return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['register','query','disable','delete'])
    args=parser.parse_args()
    try:print(json.dumps(manage(args.action),ensure_ascii=True));return 0
    except (OSError,RuntimeError,ValueError,subprocess.SubprocessError) as exc:print(str(exc),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
