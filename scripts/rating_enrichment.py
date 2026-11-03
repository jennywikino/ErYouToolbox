"""One bounded, explicit local rating batch; reuses the existing scheduler and writer."""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid
import httpx

from backfill_content_ratings import inventory, HEADERS, TIMEOUT, read_checkpoint
from run_rating_backfill import schedule
from eryoutoolbox.database import backup_database
from auto_sync import atomic_json


class RatingEnrichment:
    def __init__(self,database,root):
        self.database,self.root=Path(database),Path(root)
        self.directory=self.root/'logs/content_ratings'
        self.path=self.directory/'web_task.json'
        self.running=threading.Lock();self.cancel=threading.Event()
        try:
            self.state=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'status':'idle'}
            if not isinstance(self.state,dict):raise ValueError('Invalid rating task report')
        except (OSError,ValueError) as exc:
            self.state={'status':'stopped','error':f'Rating report unreadable; original retained: {exc}'}
        if self.state.get('status')=='checking':
            self.state={**self.state,'status':'stopped','error':'Previous API ended; resume from committed rating checkpoint.'}

    def status(self):
        counts=inventory(self.database)
        return {**self.state,'inventory':{k:v for k,v in counts.items() if k!='eligible_ids'},'running':self.running.locked()}

    def start(self,body):
        if body=={'action':'stop'}:
            self.cancel.set();return self.status()
        if (not isinstance(body,dict) or set(body)-{'action','apply','limit','retry_failed'} or body.get('action')!='run'
            or type(body.get('apply',False)) is not bool or type(body.get('retry_failed',False)) is not bool
            or type(body.get('limit',20)) is not int or not 1<=body.get('limit',20)<=20):
            raise ValueError('Rating action requires a single explicit batch, limit 1..20')
        if not self.running.acquire(blocking=False):raise ValueError('Rating batch already running')
        self.cancel.clear();self.state={'status':'checking','requests':0,'apply':body.get('apply',False),'started_at':datetime.now(timezone.utc).isoformat()}
        try:atomic_json(self.path,self.state)
        except Exception:
            self.running.release();raise
        def work():
            try:self.execute(apply=body.get('apply',False),limit=body.get('limit',20),retry_failed=body.get('retry_failed',False))
            except Exception as exc:self.state={**self.state,'status':'failed','error':str(exc)}
            finally:
                try:atomic_json(self.path,self.state)
                finally:self.running.release()
        threading.Thread(target=work,name='rating-enrichment',daemon=False).start()
        return dict(self.state)

    def execute(self,*,apply=False,limit=20,retry_failed=False,client=None):
        service=self
        class SequentialClient:
            def get(self,*args,**kwargs):
                if service.cancel.is_set():raise KeyboardInterrupt()
                service.state['requests']=service.state.get('requests',0)+1
                return active.get(*args,**kwargs)
        def backup(_):
            target=self.database.parent/'backups'/('ratings_web_'+uuid.uuid4().hex+'.db')
            backup_database(self.database,target)
            return target
        def run(active_client):
            nonlocal active
            active=active_client
            def retain_failures(batch,_):
                # Scheduler still owns the shared lock here. Operational retry
                # entries may persist without advancing committed attempts.
                if apply and batch.get('failures'):
                    checkpoint=self.directory/'checkpoint_all.json'
                    saved=read_checkpoint(checkpoint,None)
                    saved['failures'].update(batch['failures'])
                    atomic_json(checkpoint,saved)
            return schedule(self.database,self.directory/'checkpoint_all.json',client=SequentialClient(),backup_factory=backup,
                apply=apply,batches=1,limit=limit,interval=2,retry_failed=retry_failed,
                lock_path=self.directory/'instance.lock',on_batch=retain_failures)
        active=None
        if client is None:
            with httpx.Client(timeout=TIMEOUT,headers=HEADERS) as c:result=run(c)
        else:result=run(client)
        self.state={**result,'requests':result.get('totals',{}).get('requests',self.state.get('requests',0)),
                    'completed_at':datetime.now(timezone.utc).isoformat()}
        self.state.setdefault('totals',{})['candidates']=sum(b.get('save',{}).get('candidates',0) for b in result.get('batches',[]))
        # Retain bounded reports; canonical progress is the existing checkpoint, not web_task.
        atomic_json(self.directory/('web_report_'+uuid.uuid4().hex+'.json'),self.state)
        return self.state
