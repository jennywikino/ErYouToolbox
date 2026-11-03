"""Actual isolated frozen-EXE close/restart tests, optionally one source page."""
from contextlib import closing
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import time
import zipfile

from desktop_isolation_check import start,ready,request,stopped

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from backfill_content_ratings import instance_lock


def normal_close(child):
    user=ctypes.windll.user32;found=[]
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    @callback
    def visit(handle,_):
        pid=wintypes.DWORD();user.GetWindowThreadProcessId(handle,ctypes.byref(pid))
        text=ctypes.create_unicode_buffer(512);user.GetWindowTextW(handle,text,512)
        if pid.value==child.pid and text.value.startswith('妙妙二玩箱') and user.IsWindowVisible(handle):found.append(handle)
        return True
    for _ in range(200):
        user.EnumWindows(visit,0)
        if found:break
        if child.poll() is not None:raise RuntimeError('Exited before native close')
        time.sleep(.05)
    if not found:raise RuntimeError('Owned native window missing')
    user.PostMessageW(found[0],0x10,0,0)


def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--real-preview',action='store_true');args=p.parse_args()
    base=Path(tempfile.mkdtemp(prefix='F6 frozen shutdown 中文 '));exe=base/'ErYouToolbox/妙妙二玩箱.exe'
    result={'status':'BLOCK','test_directory':str(base),'production_writes':False,'real_api_requests':0,'request_budget':2 if args.real_preview else 0,'checks':[]}
    child=None;port=None
    try:
        with zipfile.ZipFile(args.archive) as z:
            for n in z.namelist():
                if not (base/n).resolve().is_relative_to(base):raise ValueError('Unsafe archive path')
            z.extractall(base)
        root=exe.parent/'userdata';db=root/'data/eryoutoolbox.db'
        def boot():
            nonlocal child,port
            child,_,log,offset=start(exe,base,seconds=60)
            port=ready(child,log,offset)
        def end(label):
            began=time.monotonic();normal_close(child);child.wait(timeout=18);stopped(child,port)
            with socket.socket() as s:
                s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
            with instance_lock(exe.parent/'.desktop.lock'):pass
            with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as c:
                assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
            result['checks'].append({'name':label,'elapsed_seconds':round(time.monotonic()-began,3),'exit':child.returncode,'port_rebind':True,'instance_lock_reacquired':True,'sqlite_integrity':'ok'})
        boot();assert request(port,'/api/mods')['total_count']==0;end('first_launch_immediate_close')
        boot();assert len(request(port,'/api/games')['games'])==6;request(port,'/api/mods')
        request(port,'/api/auto-sync',{'mode':'off','interval_hours':3,'max_pages':3});end('list_close')
        if args.real_preview:
            boot();before=hashlib.sha256(db.read_bytes()).hexdigest()
            request(port,'/api/sync',{'action':'check','game':8552,'max_pages':1})
            for _ in range(400):
                state=request(port,'/api/sync')
                if state.get('status') not in ('checking','importing'):break
                time.sleep(.1)
            result['real_api_requests']=state.get('requests',0)
            result['preview_statistics']=state.get('statistics');result['preview_status']=state.get('status')
            assert result['real_api_requests']<=2
            assert state.get('status')=='waiting',state
            assert hashlib.sha256(db.read_bytes()).hexdigest()==before
            end('real_GameBanana_preview_then_normal_close')
            boot();assert request(port,'/api/sync')['status']=='waiting';end('preview_restart_close')
        boot()
        slow=socket.create_connection(('127.0.0.1',port))
        try:
            slow.sendall((f'POST /api/sync HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\nX-ErYouToolbox: 1\r\nContent-Length: 100\r\n\r\n{{').encode())
            time.sleep(.2);end('incomplete_POST_and_native_close')
        finally:slow.close()
        # Fixture identities only, never real subscriptions or production DB.
        with closing(sqlite3.connect(db)) as c:
            c.execute("INSERT INTO mods(source,item_type,item_id,game_id,title,author_id,author_name,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',900000001,8552,'Fixture',900000002,'Fixture Author','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')");c.commit()
        boot();request(port,'/api/read-state',{'source':'gamebanana','item_id':900000001,'is_read':True});request(port,'/api/subscription',{'source':'gamebanana','author_id':900000002,'followed':True});end('temporary_read_follow_close')
        for i in range(3):
            boot();assert request(port,'/api/read-state?source=gamebanana&item_id=900000001')['is_read'];assert request(port,'/api/subscription?source=gamebanana&author_id=900000002')['followed'];assert request(port,'/api/auto-sync')['settings']['mode']=='off';end('repeat_persistence_'+str(i+1))
        boot();child.terminate();child.wait(timeout=10)
        boot();assert request(port,'/api/read-state?source=gamebanana&item_id=900000001')['is_read'];end('abnormal_exit_recovery')
        result['status']='PASS'
    except Exception as exc:
        result['error']=repr(exc)
    finally:
        if child and child.poll() is None:
            result['forced_cleanup_after_failure']=True
            child.terminate();child.wait(timeout=10)
        log=exe.parent/'userdata/logs/desktop.log'
        if log.exists():result['last_shutdown_log']=log.read_text(encoding='utf-8')[-11000:]
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='last_shutdown_log'},ensure_ascii=False,indent=2))
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
