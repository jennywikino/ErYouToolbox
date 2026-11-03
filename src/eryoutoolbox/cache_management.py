"""Explicit cache whitelist. Never deletes trees, databases, reports or locks."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time

from . import authors


def safe_child(root,path):
    root=Path(root).resolve();path=Path(path)
    if not path.absolute().is_relative_to(root) or path.absolute()==root:raise ValueError('Cache path outside approved root')
    current=path.absolute()
    while current!=root:
        if current.is_symlink() or current.is_junction():raise ValueError('Cache links are forbidden')
        current=current.parent
    resolved=path.resolve()
    if not resolved.is_relative_to(root) or resolved==root:raise ValueError('Unsafe resolved cache path')
    return resolved


def sizes(root,path):
    path=safe_child(root,path);count=total=0
    if not path.exists():return count,total
    for entry in path.rglob('*'):
        safe_child(root,entry)
        if entry.is_file():count+=1;total+=entry.stat().st_size
    return count,total


class CacheManagement:
    def __init__(self,root,popular,detail,busy=lambda:False):
        self.root=Path(root).resolve();self.popular=popular;self.detail=detail;self.busy=busy
        self.pending={};self.lock=threading.Lock();self.webview_clear=None
        self.status_path=self.root/'logs/cache_management/status.json'
    def entries(self):
        directory=safe_child(self.root,self.root/'logs/author_profiles');entries=[]
        if directory.is_dir():
            for path in directory.glob('*.json'):
                safe_child(self.root,path)
                if not re.fullmatch(r'[1-9][0-9]*\.json',path.name):continue
                try:
                    value=json.loads(path.read_text(encoding='utf-8'))
                    if (not isinstance(value,dict) or value.get('author_id')!=int(path.stem) or
                        type(value.get('expires')) not in (int,float) or value['expires']>time.time()):continue
                    entries.append(path)
                except (OSError,ValueError):continue
        return entries
    def memory(self,clear=False):
        with self.popular.recent_lock,self.popular.lock,self.detail.lock:
            caches=[self.popular.cache,self.popular.recent_cache,self.popular.board_cache,self.detail.cache]
            count=sum(len(c) for c in caches);size=sum(len(repr(c).encode('utf-8')) for c in caches) if count else 0
            if clear:
                for cache in caches:cache.clear()
            # Source cooldown clocks are intentionally retained.
            return count,size
    def status(self):
        files=self.entries();count,size=self.memory()
        browser_count,browser_size=sizes(self.root,self.root/'cache/webview')
        profiles,profile_size=sizes(self.root,self.root/'logs/ui_smoke')
        log_count,log_size=sizes(self.root,self.root/'logs')
        backup_count,backup_size=sizes(self.root,self.root/'data/backups')
        last=None
        if self.status_path.exists():last=json.loads(self.status_path.read_text(encoding='utf-8')).get('cleared_at')
        return {'last_cleared_at':last,'categories':[
            {'id':'memory','name':'热门榜与来源详情缓存','files':count,'bytes':size,'allowed':True,'scope':'内存缓存；不清除429冷却'},
            {'id':'avatars','name':'过期作者头像资料缓存','files':len(files),'bytes':sum(p.stat().st_size for p in files),'allowed':True,'scope':'仅已过期的数字ID JSON，不含图片文件'},
            {'id':'webview','name':'WebView2网页缓存','files':browser_count,'bytes':browser_size,'allowed':self.webview_clear is not None,'scope':'统计为整个浏览器资料目录；仅官方DiskCache清理，保留存储偏好，不保证释放全部占用'},
            {'id':'smoke','name':'本地测试证据和profile','files':profiles,'bytes':profile_size,'allowed':False,'scope':'未确认浏览器归属/退出，不自动删除'},
            {'id':'logs','name':'运行日志与恢复报告（总计）','files':log_count,'bytes':log_size,'allowed':False,'scope':'只读统计，含测试证据；保留正式状态、检查点、失败队列及锁'},
            {'id':'backups','name':'数据库备份','files':backup_count,'bytes':backup_size,'allowed':False,'scope':'永久排除缓存清理；外部独立备份不扫描不删除'},
        ],'protected':['SQLite/WAL/SHM','read states','subscriptions','checkpoints','settings','backups','active locks']}
    def command(self,body):
        if self.busy():raise ValueError('A sync/history task is active; cache cleanup is unavailable')
        if not isinstance(body,dict):raise ValueError('Invalid cache action')
        with self.lock:
            if body.get('action')=='preview' and set(body)=={'action','categories'}:
                ids=body['categories']
                if not isinstance(ids,list) or not ids or any(i not in ('memory','avatars','webview') for i in ids) or len(set(ids))!=len(ids):raise ValueError('Choose explicit supported cache categories')
                if 'webview' in ids and self.webview_clear is None:raise ValueError('Official WebView2 cache API unavailable')
                files=self.entries() if 'avatars' in ids else []
                snapshot={p.relative_to(self.root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
                token=secrets.token_urlsafe(24);self.pending={token:{'created':time.time(),'categories':ids,'files':snapshot}}
                return {'status':'preview','token':token,'categories':ids,'files':list(snapshot),'note':'只清理所选可再生缓存，保留数据库和个人状态'}
            if body.get('action')!='clear' or set(body)!={'action','token'}:raise ValueError('Invalid cache clear confirmation')
            plan=self.pending.pop(body['token'],None)
            if not plan or time.time()-plan['created']>300:raise ValueError('Cache preview expired; inspect again')
            # Coordinate filesystem and memory cleanup with existing writers.
            from backfill_content_ratings import instance_lock
            removed=[];errors=[]
            with instance_lock(self.root/'logs/content_ratings/instance.lock'),authors._lock:
                if self.busy():raise ValueError('Task started; cache cleanup refused')
                for name,digest in plan['files'].items():
                    path=safe_child(self.root,self.root/name)
                    if path.parent!=safe_child(self.root,self.root/'logs/author_profiles'):raise ValueError('Non-whitelisted file')
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Cache changed after preview; inspect again')
                for name in plan['files']:
                    try:safe_child(self.root,self.root/name).unlink();removed.append(name)
                    except OSError as exc:errors.append({'file':name,'error':str(exc)})
                if 'memory' in plan['categories']:self.memory(clear=True)
                if 'webview' in plan['categories']:
                    try:self.webview_clear()
                    except Exception as exc:errors.append({'category':'webview','error':str(exc)})
            from auto_sync import atomic_json
            result={'status':'partial' if errors else 'success','removed_files':removed,'errors':errors,'cleared_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
            atomic_json(self.status_path,result)
            return result
