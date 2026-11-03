"""Actual EXE acceptance in an external disposable directory, with offline fixture data.

Run with project Python. Node is only a CDP test driver, not a client dependency.
No source API, Vite, production DB or remote GameBanana request is used.
"""
from contextlib import closing
import argparse
import csv
import ctypes
from ctypes import wintypes
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import zipfile

SOURCE=Path(__file__).resolve().parents[1]
DOM = r'''
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const [port,base,evidence]=process.argv.slice(1);let target;
 for(let i=0;i<100;i++){try{target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page'&&t.url.startsWith(base));if(target)break}catch{}await delay(100)}
 if(!target)throw Error('Native WebView CDP target unavailable');
 const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});let id=0;const pending=new Map();
 ws.onmessage=e=>{const v=JSON.parse(e.data);if(v.id&&pending.has(v.id)){const [r,j,t]=pending.get(v.id);clearTimeout(t);pending.delete(v.id);v.error?j(Error(JSON.stringify(v.error))):r(v.result)}};
 const run=expression=>new Promise((r,j)=>{const n=++id,t=setTimeout(()=>j(Error('CDP timeout')),20000);pending.set(n,[v=>v.exceptionDetails?j(Error(JSON.stringify(v.exceptionDetails))):r(v.result.value),j,t]);ws.send(JSON.stringify({id:n,method:'Runtime.evaluate',params:{expression,awaitPromise:true,returnByValue:true}}))});
 const wait=async expression=>{for(let i=0;i<150;i++){if(await run(expression))return;await delay(100)}throw Error('DOM wait failed: '+expression)};
 const command=(method,params={})=>new Promise((r,j)=>{const n=++id,t=setTimeout(()=>j(Error('CDP command timeout')),20000);pending.set(n,[r,j,t]);ws.send(JSON.stringify({id:n,method,params}))});
 await wait(`document.body.innerText.includes('首次使用：选择自动化方式')`);
 await run(`(()=>{const el=document.querySelector('[aria-label="首次自动化设置"] select');const setter=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set;setter.call(el,'off');el.dispatchEvent(new Event('change',{bubbles:true}))})()`);
 await wait(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='确认并保存设置')`);
 await run(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='确认并保存设置').click()`);
 await wait(`!document.body.innerText.includes('首次使用：选择自动化方式')`);
 if(await run(`document.body.innerText.includes('内容分级')||document.body.innerText.includes('UNKNOWN')`))throw Error('Retired rating UI remains visible');
 await run(`localStorage.setItem('showPreviewImages','0');localStorage.setItem('showSensitivePreviews','0');localStorage.setItem('showUnknownPreviews','0')`);
 const fs=require('fs'),path=require('path');
 for(const [width,height] of [[1920,1080],[1366,768]]){
  await command('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});await delay(300);
  const layout=await run(`({width:innerWidth,scroll:document.documentElement.scrollWidth,columns:getComputedStyle(document.querySelector('.mod-grid')).gridTemplateColumns.split(/\s+/).length})`);
  if(layout.scroll>layout.width)throw Error('Horizontal overflow '+JSON.stringify(layout));
  const shot=await command('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(evidence,`F4-${width}.png`),Buffer.from(shot.data,'base64'));
 }
 await wait(`!!document.querySelector('[data-mod-identity="gamebanana:Mod:900000001"] button')`);
 await run(`document.querySelector('[data-mod-identity="gamebanana:Mod:900000001"] button').click()`);
 await wait(`Array.from(document.querySelectorAll('h1')).some(h=>h.textContent==='Fixture MOD')`);
 await wait(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent.trim()==='关注作者'&&!b.disabled)`);
 await run(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='关注作者').click()`);
 await wait(`document.body.innerText.includes('已关注 · 取消关注')&&document.body.innerText.includes('恢复未阅')`);
 await run(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('返回作品库')).click()`);
 await wait(`!location.hash.includes('/mod/')&&!!document.querySelector('[data-mod-identity="gamebanana:Mod:900000001"] button')`);
 await run(`history.forward()`);
 await wait(`location.hash.includes('/mod/')&&document.body.innerText.includes('恢复未阅')`);
 console.log(JSON.stringify(await run(`({hash:location.hash,title:Array.from(document.querySelectorAll('h1')).find(h=>h.textContent==='Fixture MOD').textContent,followed:document.body.innerText.includes('已关注 · 取消关注'),read:document.body.innerText.includes('恢复未阅')})`)));
 ws.close();
})().catch(e=>{console.error(e);process.exitCode=1});
'''


def spare_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def start(exe, cwd, seconds=8, debug=False):
    env=dict(os.environ,PATH=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot'],PYTHONHOME='',PYTHONPATH='')
    port=spare_port() if debug else None
    if debug:env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=f'--remote-debugging-address=127.0.0.1 --remote-debugging-port={port}'
    log=exe.parent/'userdata/logs/desktop.log'
    offset=len(log.read_text(encoding='utf-8')) if log.exists() else 0
    child=subprocess.Popen([str(exe),'--smoke-seconds',str(seconds)],cwd=cwd,env=env)
    return child,port,log,offset


def ready(child,log,offset):
    for _ in range(200):
        if log.exists():
            match=re.search(r'ready: http://127.0.0.1:(\d+)/',log.read_text(encoding='utf-8')[offset:])
            if match:return int(match[1])
        if child.poll() is not None:raise RuntimeError(f'EXE exited before ready: {child.returncode}')
        time.sleep(.1)
    raise RuntimeError('API did not become ready')


def request(port,path,body=None):
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
    try:
        headers={'Origin':f'http://127.0.0.1:{port}','X-ErYouToolbox':'1','Content-Type':'application/json'}
        c.request('GET' if body is None else 'POST',path,json.dumps(body) if body is not None else None,headers);response=c.getresponse();raw=response.read()
        if response.status!=200:raise RuntimeError(f'{path}: HTTP {response.status}')
        return json.loads(raw)
    finally:c.close()


def stopped(child,port):
    child.wait(timeout=40)
    if child.returncode:raise RuntimeError(f'EXE exit: {child.returncode}')
    with socket.socket() as sock:
        sock.settimeout(1)
        if sock.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('API port still occupied after exit')


def close_error(child):
    # Close only the native error dialog owned by this exact Popen child.
    user=ctypes.windll.user32
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    found=[]
    def text(handle):
        buffer=ctypes.create_unicode_buffer(4096);user.GetWindowTextW(handle,buffer,4096);return buffer.value
    @callback
    def window(handle,_):
        pid=wintypes.DWORD();user.GetWindowThreadProcessId(handle,ctypes.byref(pid))
        if pid.value==child.pid and text(handle)=='妙妙二玩箱启动失败':found.append(handle)
        return True
    for _ in range(150):
        user.EnumWindows(window,0)
        if found:break
        if child.poll() is not None:break
        time.sleep(.1)
    if not found:raise RuntimeError('Expected owned error dialog not found')
    lines=[]
    @callback
    def content(handle,_):
        lines.append(text(handle));return True
    # The HWND may appear before MessageBox finishes creating its Static text.
    # Wait for actual error text instead of closing a half-created dialog.
    for _ in range(60):
        lines.clear();user.EnumChildWindows(found[0],content,0)
        if any(line.strip() and line.strip() not in ('确定','OK','&OK') for line in lines):break
        time.sleep(.05)
    user.PostMessageW(found[0],0x0010,0,0)
    child.wait(timeout=10)
    if child.returncode==0:raise RuntimeError('Error startup reported success')
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    base=Path(tempfile.mkdtemp(prefix='ErYouToolbox 独立验收 ')).resolve()
    if base.is_relative_to(SOURCE):raise RuntimeError('Test directory must be outside source')
    cwd=base/'无关 工作目录';cwd.mkdir()
    report={'status':'BLOCK','test_directory':str(base),'production_writes':False,'real_api_requests':0,'checks':{}}
    try:
        with zipfile.ZipFile(args.archive) as archive:
            for name in archive.namelist():
                if not (base/name).resolve().is_relative_to(base):raise ValueError('Unsafe archive path')
            archive.extractall(base)
        exe=base/'ErYouToolbox/妙妙二玩箱.exe'
        # Missing resources must fail even though the source directory still has all configs.
        manifest=json.loads((exe.parent/'_internal/RESOURCE_MANIFEST.json').read_text(encoding='utf-8'))
        javascript=next(n for n in manifest['files'] if n.endswith('.js'))
        for relative in ('assets/branding/MiaomiaoEryouxiang_icon.ico','assets/branding/MiaomiaoEryouxiang_icon.png','config/games.json','frontend/dist/index.html',javascript):
            resource=exe.parent/'_internal'/relative
            original=resource.read_bytes();resource.unlink()
            try:
                child,_,_,_=start(exe,cwd)
                message=close_error(child)
                if str(resource) not in message:raise RuntimeError(f'Incomplete resource error: {message}')
                if (exe.parent/'userdata').exists():raise RuntimeError('Failed preflight created userdata')
                report['checks']['missing_'+relative]=message
            finally:resource.write_bytes(original)
        child,_,log,offset=start(exe,cwd)
        port=ready(child,log,offset)
        report['checks']['games']=len(request(port,'/api/games')['games'])
        for _ in range(100):
            cache=request(port,'/api/cache')
            if next(c for c in cache['categories'] if c['id']=='webview')['allowed']:break
            time.sleep(.1)
        plan=request(port,'/api/cache',{'action':'preview','categories':['memory','webview']})
        cleared=request(port,'/api/cache',{'action':'clear','token':plan['token']})
        if cleared['status']!='success':raise RuntimeError('Official WebView2 cache clear failed: '+str(cleared))
        report['checks']['official_disk_cache_clear']=True
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        connection.request('GET','/api/rating-enrichment');retired=connection.getresponse();retired.read();connection.close()
        if retired.status!=410:raise RuntimeError('Rating job still accessible')
        report['checks']['rating_job_retired']=True
        if (exe.parent/'userdata/logs/content_ratings/checkpoint_all.json').exists():raise RuntimeError('Retired feature created rating checkpoint')
        stopped(child,port)
        # Deny writes only on this test-owned userdata directory; restore ACL immediately.
        data=exe.parent/'userdata'
        sid=re.search(r'S-1-5-[0-9-]+',subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True)).group()
        subprocess.run(['icacls',str(data),'/deny',f'*{sid}:(WD,AD)'],capture_output=True,check=True)
        try:
            failed,_,_,_=start(exe,cwd)
            report['checks']['unwritable_userdata']=close_error(failed)
            if str(data) not in report['checks']['unwritable_userdata'].replace('\\\\','\\'):raise RuntimeError('Missing unwritable userdata path')
        finally:subprocess.run(['icacls',str(data),'/remove:d',f'*{sid}'],capture_output=True,check=True)
        report['checks']['first_window']=json.loads((exe.parent/'userdata/logs/desktop-smoke.json').read_text(encoding='utf-8'))
        brand=report['checks']['first_window']
        if brand.get('window_title')!='妙妙二玩箱' or brand['page']['title']!='妙妙二玩箱 · MOD 作品库' or not brand.get('window_icon_matches_brand'):
            raise RuntimeError('Native title, page title, or window icon does not match the supplied brand')
        db=exe.parent/'userdata/data/eryoutoolbox.db'
        with closing(sqlite3.connect(db)) as c:
            c.execute("INSERT INTO mods(source,item_type,item_id,game_id,game_name,title,author_id,author_name,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',900000001,8552,'Genshin Impact','Fixture MOD',900000002,'Fixture Author','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")
            c.commit()
        # Preseed only the isolated fixture's negative avatar cache. The native
        # detail component must not turn an offline smoke into a source request.
        cache=exe.parent/'userdata/logs/author_profiles';cache.mkdir(parents=True,exist_ok=True)
        (cache/'900000002.json').write_text(json.dumps({'author_id':900000002,'avatar_url':None,'expires':time.time()+86400}),encoding='utf-8')
        child,debug,log,offset=start(exe,cwd,seconds=20,debug=True)
        port=ready(child,log,offset)
        driver=subprocess.run([shutil.which('node'),'-e',DOM,str(debug),f'http://127.0.0.1:{port}/',str(args.report.resolve().parent)],capture_output=True,text=True,encoding='utf-8',timeout=40)
        if driver.returncode:raise RuntimeError(driver.stderr)
        report['checks']['native_detail_read_follow']=json.loads(driver.stdout)
        duplicate,_,_,_=start(exe,cwd)
        report['checks']['duplicate']=close_error(duplicate)
        stopped(child,port)
        # Real directory move outside source; same userdata, new executable path and cwd.
        moved=base/'已迁移 中文 客户端';shutil.move(exe.parent,moved);exe=moved/'妙妙二玩箱.exe'
        child,_,log,offset=start(exe,base)
        port=ready(child,log,offset)
        read=request(port,'/api/read-state?source=gamebanana&item_id=900000001')
        automation=request(port,'/api/auto-sync')
        if not automation.get('configured') or automation['settings']['mode']!='off' or automation['settings']['interval_hours']!=3:raise RuntimeError('First-use consent settings did not persist')
        report['checks']['consent_persisted']=True
        follow=request(port,'/api/subscription?source=gamebanana&author_id=900000002')
        if not read['is_read'] or not follow['followed']:raise RuntimeError('State did not persist')
        report['checks']['moved_restart']={'is_read':read['is_read'],'followed':follow['followed']}
        stopped(child,port)
        # Kill only this directly launched, idle EXE. No transaction is in progress.
        child,_,log,offset=start(exe,cwd,seconds=30)
        port=ready(child,log,offset)
        child.terminate();child.wait(timeout=10)
        with socket.socket() as sock:
            sock.settimeout(1)
            if sock.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('Crashed EXE retained its API port')
        if not (exe.parent/'.desktop.lock').exists():raise RuntimeError('Lock file unexpectedly deleted')
        child,_,log,offset=start(exe,cwd)
        port=ready(child,log,offset)
        if not request(port,'/api/read-state?source=gamebanana&item_id=900000001')['is_read']:raise RuntimeError('Crash lost read state')
        stopped(child,port)
        report['checks']['abnormal_exit_restart']=True
        report['status']='PASS'
    except Exception as exc:
        report['error']=repr(exc)
    finally:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
