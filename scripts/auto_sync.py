"""One-shot automatic sync; default off, no browser or background service."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from web_sync import WebSync, utc
from backfill_content_ratings import instance_lock

DEFAULTS={'mode':'off','interval_hours':6,'max_pages':3}

def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)

def identity(root):
    import uuid
    value=json.loads((Path(root)/'config/project_identity.json').read_text(encoding='utf-8'))['project_id']
    return str(uuid.UUID(value))

def validate_root(root):
    root=Path(root).resolve()
    identity(root)
    for name in ('data/eryoutoolbox.db','config/games.json','scripts/auto_sync.py','src/eryoutoolbox/gamebanana.py'):
        if not (root/name).is_file():raise ValueError(f'Missing existing project file: {name}')
    return root

def runtime_dir(root):
    local=os.environ.get('LOCALAPPDATA')
    if not local:raise ValueError('LOCALAPPDATA is required')
    return Path(local)/'ErYouToolbox/auto_sync'/identity(root)

class AutoSync:
    def __init__(self,root,database=None,games=None,state_dir=None):
        self.root=Path(root);self.database=Path(database) if database else self.root/'data/eryoutoolbox.db'
        self.games=games
        self.directory=Path(state_dir) if state_dir else runtime_dir(self.root)
        self.running=threading.Lock()

    def launch(self, *, startup=False):
        if self.settings()['mode']=='off':
            if startup:return {'status':'disabled','requests':0}
            raise ValueError('Automatic sync is disabled')
        if not self.running.acquire(blocking=False):
            if startup:return {'status':'already_running','requests':0}
            raise ValueError('Automatic sync already running')
        def target():
            try:self.run(force=not startup,preserve_preview=startup)
            except Exception as exc:
                if 'Another rating backfill instance is active' not in str(exc):
                    atomic_json(self.directory/'last_run.json',{'status':'failed','started_at':utc(),'started_epoch':time.time(),'error':str(exc),'requests':0})
            finally:self.running.release()
        # Browser lifetime must not own the job. A normal server shutdown can
        # finish the bounded worker rather than abandoning an active transaction.
        threading.Thread(target=target,daemon=False).start()
        return {'status':'requested'}

    def settings(self):
        path=self.directory/'settings.json'
        value=json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(DEFAULTS)
        self.validate(value);return value

    @staticmethod
    def validate(value):
        if not isinstance(value,dict) or set(value)!=set(DEFAULTS):raise ValueError('Invalid automatic sync settings')
        if value['mode'] not in ('off','check','apply'):raise ValueError('Invalid automatic sync mode')
        for name,low,high in [('interval_hours',1,168),('max_pages',1,10)]:
            if type(value[name]) is not int or not low<=value[name]<=high:raise ValueError(f'{name} must be {low}..{high}')

    def configure(self,value):
        self.validate(value)
        with instance_lock(self.directory/'settings.lock'):
            atomic_json(self.directory/'settings.json',value)
        return self.status()

    def history(self):
        from history_sync import HistorySync
        return HistorySync(self.root,self.database,self.games,mode_provider=self.settings)

    def run_history(self):
        # Caller already owns the same OS lock. Never reacquire it here.
        try:return self.history().run(lock_held=True)
        except (OSError,ValueError) as exc:return {'status':'failed','requests':0,'error':str(exc)}

    def status(self):
        settings=self.settings();last=self.directory/'last_run.json'
        record=json.loads(last.read_text(encoding='utf-8')) if last.exists() else None
        if record and record['status']=='manual_preview_pending' and self.database.is_file():
            current=WebSync(self.database,self.root,self.games or [])
            if (current.state['status']!='waiting' or not current.candidate or
                time.time()-current.candidate['created']>600):
                record={**record,'status':'preview_resolved','error':None}
        if record and record['status']=='checking' and self.database.is_file():
            try:
                with instance_lock(self.root/'logs/content_ratings/instance.lock'):
                    recovered=WebSync(self.database,self.root,self.games or []).view()
                    status=recovered['status']
                    record={**record,'status':'stopped' if status in ('checking','importing','idle') else status,
                            'error':'Previous process ended; use immediate run to resume with overlap'}
            except RuntimeError:
                pass  # Active worker owns the lock; keep its live checking state.
        next_check=None
        if settings['mode']!='off':
            due=(record.get('started_epoch',0) if record else 0)+settings['interval_hours']*3600
            next_check=datetime.fromtimestamp(max(time.time(),due,record.get('not_before',0) if record else 0),timezone.utc).isoformat()
        registration=self.directory/'registration.json'
        task=json.loads(registration.read_text(encoding='utf-8')) if registration.exists() else {'registered':False}
        return {'settings':settings,'last_run':record,'next_due':next_check,'task':task}

    def run(self,*,force=False,dry_run=False,max_pages=None,game=None,preserve_preview=False):
        # A missing disk must not create an empty SQLite database.
        if not self.database.is_file():raise ValueError('Existing database required')
        settings=self.settings();mode='check' if dry_run else settings['mode']
        if mode=='off':return {'status':'disabled','requests':0}
        # Keep the same lock across check and apply, not two independent write entrances.
        with instance_lock(self.root/'logs/content_ratings/instance.lock'):
            previous=self.status()['last_run']
            now=time.time()
            history_cooldown=self.history().cooldown_until()
            if now<history_cooldown:return {'status':'cooldown','not_before':history_cooldown,'requests':0}
            if previous and now<previous.get('not_before',0):return {'status':'cooldown','not_before':previous['not_before'],'requests':0}
            if not force and previous and previous['status'] not in ('manual_preview_pending','preview_resolved') and now<previous['started_epoch']+settings['interval_hours']*3600:
                history={'status':'not_requested','requests':0} if dry_run else self.run_history()
                if history.get('not_before'):
                    atomic_json(self.directory/'last_run.json',{**previous,'not_before':history['not_before']})
                return {'status':'not_due','requests':history.get('requests',0),'history':history}
            service=WebSync(self.database,self.root,self.games or json.loads((self.root/'config/games.json').read_text(encoding='utf-8'))['games'])
            old=service.view()
            if old['status']=='waiting' and (preserve_preview or not old.get('automatic')) and service.candidate and now-service.candidate['created']<=600:
                deferred={'status':'manual_preview_pending','started_epoch':now,'started_at':utc(),'requests':0,
                          'error':'Manual preview awaits confirmation; automatic job did not replace it'}
                atomic_json(self.directory/'last_run.json',deferred)
                return deferred
            budget=max_pages if max_pages is not None else settings['max_pages']
            if type(budget) is not int or not 1<=budget<=10:raise ValueError('max_pages must be 1..10')
            games=service.games if game is None else [g for g in service.games if g['game_id']==game]
            if not games or len(games)>6:raise ValueError('Unknown game or too many games')
            service.task_id=secrets.token_hex(16);service.state={'status':'checking','game_id':game,'automatic':True}
            record={'status':'checking','started_at':utc(),'started_epoch':now,'mode':mode,'requests':0}
            atomic_json(self.directory/'last_run.json',record)
            try:
                service.save();service.check_games(games,10,budget,True)
                service.state['automatic']=True
                service.save()
                if mode=='apply' and service.state['status']=='waiting':
                    # Re-read opt-in immediately before the importer begins its transaction.
                    def write_guard():
                        if self.settings()['mode']!='apply':raise ValueError('Automatic apply was disabled during check')
                    write_guard()
                    service.apply(only_source_changes=True,write_guard=write_guard)
                state=service.view()
                record.update(status=state['status'],ended_at=utc(),requests=state.get('requests',0),
                              scanned=state.get('scanned',0),statistics=state.get('statistics'),
                              failures=state.get('failures',[]),coverage=state.get('coverage','incomplete'),
                              inserted=state.get('report',{}).get('inserted',0),source_updated=state.get('report',{}).get('source_update_events',0))
                if state.get('scan_status')=='rate_limited':record['not_before']=time.time()+settings['interval_hours']*3600
                else:
                    from eryoutoolbox.author_updates import run_rotation
                    from eryoutoolbox.gamebanana import TIMEOUT,HEADERS
                    import httpx
                    with httpx.Client(timeout=TIMEOUT,headers=HEADERS) as client:
                        def author_guard():
                            if self.settings()['mode']!='apply':raise ValueError('Automatic apply disabled')
                        try:
                            authors=run_rotation(self.database,self.root,client=client,apply=mode=='apply',advance=not dry_run,write_guard=author_guard)
                        except (OSError,ValueError,httpx.HTTPError) as exc:
                            authors={'status':'failed','requests':0,'error':str(exc)}
                    record['authors']={k:authors.get(k) for k in ('status','requests','followed_count','checked_authors','pending_count')}
                    if authors.get('error'):record['authors']['error']=authors['error']
                    record['requests']+=authors['requests']
                    if authors.get('rate_limited_at'):record['not_before']=time.time()+max(authors.get('retry_after_seconds') or settings['interval_hours']*3600,1)
                    if authors['status']!='success':record['status']='partial'
                if state['status']=='failed':record['error']=state.get('error','No validated pages')
                if not dry_run and not record.get('not_before') and state['status']!='failed':
                    history=self.run_history()
                    record['history']={k:history.get(k) for k in ('status','requests','coverage')}
                    record['requests']+=history.get('requests',0)
                    if history.get('not_before'):record['not_before']=history['not_before']
                    if history['status'] in ('failed','partial','stopped'):record['status']='partial'
            except BaseException as exc:
                record.update(status='stopped' if isinstance(exc,KeyboardInterrupt) else 'failed',ended_at=utc(),error=str(exc),requests=service.state.get('requests',0))
                service.state={**service.state,'status':record['status'],'error':str(exc)}
                try:service.save()
                except (OSError,ValueError):pass
                atomic_json(self.directory/'last_run.json',record)
                if isinstance(exc,KeyboardInterrupt):raise
                return record
            record['ended_at']=utc()
            atomic_json(self.directory/'last_run.json',record)
            atomic_json(self.directory/('run_'+secrets.token_hex(12)+'.json'),record)
            return record

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-now',action='store_true',help='Ignore normal interval; never bypass rate-limit cooldown')
    parser.add_argument('--dry-run',action='store_true',help='Explicit one-shot check even if automatic mode is off')
    parser.add_argument('--max-pages',type=int)
    parser.add_argument('--game',type=int,help='Optional bounded single-game verification')
    parser.add_argument('--mode',choices=['off','check','apply'],help='Save device setting without running')
    parser.add_argument('--interval-hours',type=int)
    args=parser.parse_args()
    try:
        root=validate_root(ROOT);auto=AutoSync(root)
        if args.mode is not None or args.interval_hours is not None:
            settings=auto.settings()
            if args.mode is not None:settings['mode']=args.mode
            if args.interval_hours is not None:settings['interval_hours']=args.interval_hours
            if args.max_pages is not None:settings['max_pages']=args.max_pages
            result=auto.configure(settings)
        else:result=auto.run(force=args.run_now,dry_run=args.dry_run,max_pages=args.max_pages,game=args.game)
        print(json.dumps(result,ensure_ascii=True))
        return 1 if result.get('status')=='failed' else 0
    except (OSError,ValueError,RuntimeError) as exc:
        print(f'Automatic sync stopped: {exc}',file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
