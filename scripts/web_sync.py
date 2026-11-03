"""Bounded web sync, durable previews and transactional committed checkpoints."""
import hashlib
import json
import secrets
import threading
import time
import math
from pathlib import Path

import httpx
from eryoutoolbox.database import backup_database, connect_database
from eryoutoolbox.gamebanana import collect_game, HEADERS, TIMEOUT
from eryoutoolbox.importer import import_samples, parse_utc
from eryoutoolbox.ui_queries import readonly_connection
from backfill_content_ratings import instance_lock

FORMAT='eryoutoolbox-web-sync-v1'
MAX_PAGES=10


def recent_window(record, captured_at, days=90):
    """Local discovery time and modified_at never establish source activity."""
    from datetime import timedelta
    cutoff=parse_utc(captured_at)-timedelta(days=days)
    dates=[parse_utc(record.get(key)) for key in ('created_at','updated_at')]
    dates=[value for value in dates if value is not None]
    if not dates:return 'missing_dates'
    return 'in_window' if any(cutoff<=value<=parse_utc(captured_at) for value in dates) else 'out_of_window'

def utc():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())

def fingerprint(c):
    rows=[tuple(r) for r in c.execute('SELECT * FROM mods ORDER BY source,item_type,item_id')]
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()

def classify(report, fetched, page_duplicates=0):
    unique=report['unique_records']
    values={'new':report['inserted'],'source_updated':report['source_update_events'],
            'metadata_only':report['updated']-report['source_update_events'],
            'unchanged':report['unchanged'],'skipped':report['skipped']}
    return {'fetched':fetched,'unique':unique,'duplicates':report['batch_duplicates']+page_duplicates,
            'unclassified':max(0,fetched-report['input_records']-page_duplicates),
            'classified':sum(values.values()),**values}

def page_plan(frontier, budget):
    # Always refresh head and overlap the committed frontier; never assume no drift.
    if frontier<=1:return list(range(1,budget+1))
    return [1]+list(range(max(2,frontier),max(2,frontier)+budget-1))

class WebSync:
    def __init__(self,database,root,games):
        self.database,self.root,self.games=Path(database),Path(root),games
        self.mutex=threading.Lock();self.cancel=threading.Event()
        self.worker_active=False
        self.state={'status':'idle'};self.candidate=None;self.task_id=secrets.token_hex(16)
        self.path=self.root/'logs/web_sync/task.json'
        self.binding=self.database.resolve().relative_to(self.root.resolve()).as_posix()
        if self.path.exists():
            try:
                saved=json.loads(self.path.read_text(encoding='utf-8'))
                if saved['format']!=FORMAT or saved['database']!=self.binding:raise ValueError('Task identity mismatch')
                self.state=saved['state'];self.task_id=saved['task_id'];self.candidate=saved.get('candidate')
                if self.candidate:
                    for meta,_ in self.candidate['snapshots']:meta['captured_at']=parse_utc(meta['captured_at'])
                if self.state['status'] in ('checking','importing'):
                    try:
                        with instance_lock(self.root/'logs/content_ratings/instance.lock'):
                            self.state={**self.state,'status':'stopped','scan_status':'awaiting_resume','error':'API interrupted; resume with overlap recheck'}
                            self.candidate=None
                    except RuntimeError:
                        pass  # Another process still owns the shared sync lock.
                c=readonly_connection(self.database)
                try:
                    for row in c.execute('SELECT error_summary FROM sync_runs ORDER BY run_id DESC'):
                        data=json.loads(row[0] or '{}').get('web_sync',{})
                        if data.get('task_id')==self.task_id:
                            self.state={**self.state,'status':'partial' if self.state.get('failures') else 'success','checkpoint_committed':True}
                            self.candidate=None;break
                finally:c.close()
            except Exception as exc:
                self.state={'status':'failed','error':f'Cannot restore task; original file retained: {exc}'}
        self.disk_stamp=self.path.stat().st_mtime_ns if self.path.exists() else None

    def refresh(self):
        if self.worker_active:return
        stamp=self.path.stat().st_mtime_ns if self.path.exists() else None
        if stamp is not None and (stamp!=self.disk_stamp or self.state['status'] in ('checking','importing')):
            other=WebSync(self.database,self.root,self.games)
            with self.mutex:
                if not self.worker_active:
                    self.state,self.candidate,self.task_id=other.state,other.candidate,other.task_id
                    self.disk_stamp=stamp

    def save(self):
        with self.mutex:
            value={'format':FORMAT,'database':self.binding,'task_id':self.task_id,'state':self.state,'candidate':self.candidate}
            raw=json.dumps(value,ensure_ascii=False,default=lambda v:v.isoformat(),indent=2)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.exists():
            previous=json.loads(self.path.read_text(encoding='utf-8'))
            if previous.get('format')!=FORMAT or previous.get('database')!=self.binding:
                raise ValueError('Existing task journal identity invalid; file retained')
            if previous['task_id']!=self.task_id:
                archive=self.path.with_name('previous_'+secrets.token_hex(12)+'.json')
                archive.write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')
        temp=self.path.with_name('task_'+secrets.token_hex(8)+'.tmp')
        temp.write_text(raw,encoding='utf-8');temp.replace(self.path)
        self.disk_stamp=self.path.stat().st_mtime_ns

    def committed(self):
        c=readonly_connection(self.database);out={}
        try:
            for row in c.execute('SELECT error_summary FROM sync_runs ORDER BY run_id DESC'):
                data=json.loads(row[0] or '{}').get('web_sync',{})
                for gid,cp in data.get('checkpoints',{}).items():out.setdefault(gid,cp)
        finally:c.close()
        return out

    def view(self):
        self.refresh()
        with self.mutex:return json.loads(json.dumps(self.state))

    def check_cooldown(self):
        path=self.root/'logs/history_sync/cooldown.json'
        if path.exists() and time.time()<json.loads(path.read_text(encoding='utf-8')).get('not_before',0):
            raise ValueError('GameBanana cooldown active; Retry-After has not elapsed')

    def start(self,body):
        self.refresh()
        if body.get('action')=='discard':
            with instance_lock(self.root/'logs/content_ratings/instance.lock'):
                self.refresh()
                with self.mutex:
                    if (set(body)!={'action','token','game'} or self.worker_active or
                        self.state['status']!='waiting' or body['token']!=self.state.get('token') or
                        body['game']!=self.state.get('game_id')):
                        raise ValueError('Preview changed; refresh before discarding')
                    archive=self.path.with_name('discarded_'+secrets.token_hex(12)+'.json')
                    archive.write_bytes(self.path.read_bytes())
                    self.candidate=None
                    self.state={**self.state,'status':'discarded','token':None}
                self.save()
                return self.view()
        with self.mutex:
            if body=={'action':'stop'}:
                if self.state['status']=='checking':self.cancel.set()
                return dict(self.state)
            if self.state['status'] in ('checking','importing'):raise ValueError('A sync is already running')
            action=body.get('action')
            if action in ('check','check_all','resume'):
                self.check_cooldown()
                required={'action'} if action=='check_all' else {'action','game'}
                if not required<=set(body) or set(body)-required-{'max_pages'}:raise ValueError('Invalid check request')
                budget=body.get('max_pages',3)
                if type(budget) is not int or not 1<=budget<=MAX_PAGES:raise ValueError('max_pages must be 1..10')
                gid=None if action=='check_all' else body['game']
                selected=self.games if gid is None and action!='check' else [g for g in self.games if type(gid) is int and g['game_id']==gid]
                if not selected or len(selected)>6:raise ValueError('Choose supported games (at most six)')
                self.candidate=None;self.cancel.clear();self.task_id=secrets.token_hex(16)
                self.state={'status':'checking','game_id':gid,'completed':0,'games':[],'max_pages':budget}
                target,args=self.check_games,(selected,10 if len(selected)>1 else 20,budget,action=='resume',90)
            elif action=='confirm' and set(body)=={'action','token','game'}:
                if not self.candidate or self.state['status']!='waiting' or body['token']!=self.state['token'] or body['game']!=self.state['game_id']:raise ValueError('Preview identity mismatch; check again')
                if time.time()-self.candidate['created']>600:raise ValueError('Preview expired; check again')
                self.state={**self.state,'status':'importing'};target,args=self.apply,()
            else:raise ValueError('Invalid sync request')
            self.worker_active=True
            threading.Thread(target=self.work,args=(target,args),daemon=True).start()
            return dict(self.state)

    def work(self,target,args):
        try:
            with instance_lock(self.root/'logs/content_ratings/instance.lock'):
                self.save();target(*args)
        except Exception as exc:
            with self.mutex:self.state={**self.state,'status':'failed','error':str(exc)}
            # Never replace another instance's task when acquiring the lock failed.
            if 'Another rating backfill' not in str(exc):
                try:self.save()
                except OSError:pass
        finally:self.worker_active=False

    def check(self,game):self.check_games([game],20)

    def check_games(self,games,per_page=10,max_pages=3,resume=False,window_days=None):
        self.check_cooldown()
        if not 1<=len(games)<=6 or type(max_pages) is not int or not 1<=max_pages<=MAX_PAGES:raise ValueError('Bounded games/pages required')
        if per_page not in (10,20):raise ValueError('Invalid web page size')
        checkpoints=self.committed();summaries=[];snapshots=[];identities={};stopped=False
        with self.mutex:self.state={**self.state,'status':'checking','game_id':games[0]['game_id'] if len(games)==1 else None,'games':summaries}
        with httpx.Client(timeout=TIMEOUT,headers=HEADERS) as client:
            for game in games:
                cp=checkpoints.get(str(game['game_id']),{})
                # A changed page size cannot safely reuse old page numbers.
                frontier=cp.get('frontier',0) if resume and cp.get('per_page')==per_page else 0
                plan=page_plan(frontier,max_pages)
                summary={'game_id':game['game_id'],'name':game['name'],'status':'skipped','scanned':0,'requests':0,
                         'failures':[],'pages':[],'planned_pages':plan,'coverage':'incomplete','checkpoint':cp,
                         'frontier':frontier,'per_page':per_page,'known_ids':[],'newest_known':{},'page_duplicates':0,'scan_status':'awaiting_resume'}
                summary.update(window_days=window_days,out_of_window=0,missing_dates=0,
                               pending_date_ids=list(cp.get('pending_date_ids',[])))
                summaries.append(summary)
                if stopped or self.cancel.is_set():
                    summary['failures']=[{'reason':'Not requested after stop signal'}];continue
                for page in plan:
                    if self.cancel.is_set():stopped=True;break
                    with self.mutex:self.state={**self.state,'current_game':game['name'],'current_page':page,'completed':len(summaries)-1,'games':summaries}
                    result=None
                    try:
                        result=collect_game(client,game,max_pages=1,per_page=per_page,days=window_days or 30,sort='Generic_NewAndUpdated',start_page=page,max_requests=2,max_rate_wait=0)
                        summary['requests']+=result['request_count']
                        fetched=sum(p.get('returned_count',0) for p in result.get('pagination_pages',[])) if result.get('pagination_pages') else result['actual_record_count']
                        summary['scanned']+=fetched
                        failures=result['failure_reasons']
                        if failures:
                            summary['failures'].extend(failures)
                            stopped=any(f.get('http_status') in (429,403) or f.get('stop_requested') for f in failures)
                            if stopped:
                                from auto_sync import atomic_json
                                waits=[f.get('retry_after_seconds') for f in failures]
                                wait=max([10800]+[w for w in waits if type(w) in (int,float) and math.isfinite(w) and w>=0])
                                atomic_json(self.root/'logs/history_sync/cooldown.json',{'not_before':time.time()+wait,'http_status':next((f.get('http_status') for f in failures if f.get('http_status') in (429,403)),None),'observed_at':utc()})
                            summary['scan_status']='rate_limited' if stopped else 'check_failed'
                            break
                        if fetched>per_page or len(result['records'])>per_page:raise ValueError('Source exceeded candidate limit')
                        for record in result['records']:
                            key=(record.get('source'),record.get('item_type'),record.get('item_id'))
                            if (key[0]!='gamebanana' or key[1]!='Mod' or type(key[2]) is not int or key[2]<=0 or record.get('game_id')!=game['game_id'] or key in identities and identities[key]!=game['game_id']):raise ValueError('Source identity mismatch')
                        for r in result['records']:identities[(r['source'],r['item_type'],r['item_id'])]=game['game_id']
                        summary['page_duplicates']+=max(0,result['actual_record_count']-len(result['records']))
                        selected=[]
                        for r in result['records']:
                            scope=recent_window(r,result['collected_at'],window_days) if window_days else 'in_window'
                            if scope=='missing_dates':
                                if r['item_id'] not in summary['pending_date_ids']:summary['pending_date_ids'].append(r['item_id'])
                            elif r['item_id'] in summary['pending_date_ids']:summary['pending_date_ids'].remove(r['item_id'])
                            if scope=='in_window':selected.append(r)
                            else:summary[scope]+=1
                        snapshots.append(({'captured_at':parse_utc(result['collected_at'])},selected))
                        summary['pages'].append(page)
                        summary['known_ids']=list(dict.fromkeys(summary['known_ids']+[r['item_id'] for r in result['records']]))[:200]
                        for field in ('created_at','updated_at'):
                            candidates=[r for r in result['records'] if parse_utc(r.get(field))]
                            if candidates:
                                newest=max(candidates,key=lambda r:parse_utc(r[field]))
                                previous=summary['newest_known'].get(field)
                                if not previous or parse_utc(newest[field])>parse_utc(previous['timestamp']):
                                    summary['newest_known'][field]={'item_id':newest['item_id'],'timestamp':newest[field]}
                        if page<=summary['frontier']+1:summary['frontier']=max(summary['frontier'],page)
                        summary['status']='success';summary['checked_at']=result['collected_at']
                        summary['scan_status']='incomplete'
                        self.save()
                        if result.get('pagination_pages') and result['pagination_pages'][-1].get('end_of_results'):
                            summary['scan_status']='complete_check';break
                    except Exception as exc:
                        summary['failures'].append({'page':page,'reason':str(exc)});summary['scan_status']='check_failed';break
                    time.sleep(1)
                if self.cancel.is_set():summary['scan_status']='awaiting_resume'
                if summary['failures'] or self.cancel.is_set():summary['status']='partial' if summary['pages'] else 'failed'
                # A preview journal never advances the committed checkpoint.
                with self.mutex:self.state={**self.state,'games':summaries,'completed':len(summaries)}
                self.save()
        self.finish_preview(summaries,snapshots,games)

    def finish_preview(self,summaries,snapshots,games):
        c=readonly_connection(self.database)
        try:
            c.execute('BEGIN');baseline=fingerprint(c)
            sync_generation=c.execute('SELECT COALESCE(MAX(run_id),0) FROM sync_runs').fetchone()[0]
            grouped={g['game_id']:[] for g in games}
            for meta,records in snapshots:
                for record in records:
                    old=c.execute('SELECT preview_urls_json,content_rating_status FROM mods WHERE source=? AND item_type=? AND item_id=?',('gamebanana','Mod',record['item_id'])).fetchone()
                    if old:
                        if old['preview_urls_json']:record['preview_images']=json.loads(old['preview_urls_json'])
                        record['content_rating_status']=old['content_rating_status']
                if records:grouped[records[0]['game_id']].append((meta,records))
            report=import_samples(c,snapshots,dry_run=True)
            for s in summaries:
                s['report']=import_samples(c,grouped[s['game_id']],dry_run=True)
                s['statistics']=classify(s['report'],s['scanned'],s['page_duplicates'])
                s['statistics'].update(out_of_window=s.get('out_of_window',0),missing_dates=s.get('missing_dates',0))
                excluded=s.get('out_of_window',0)+s.get('missing_dates',0)
                s['statistics']['classified']+=excluded
                s['statistics']['unclassified']=max(0,s['statistics']['unclassified']-excluded)
                s['missing_update_evidence']=sum(not r.get('updated_at') for _,rows in grouped[s['game_id']] for r in rows)
        finally:c.close()
        records=[r for _,rows in snapshots for r in rows]
        errors=[{'game_id':s['game_id'],**f} for s in summaries for f in s['failures']]
        if self.cancel.is_set():errors.append({'reason':'Stopped by user; uncommitted pages will be rechecked'})
        result={'collected_at':utc(),'records':records,'failure_reasons':errors,'actual_record_count':sum(s['scanned'] for s in summaries),'request_count':sum(s['requests'] for s in summaries)}
        with self.mutex:
            self.candidate={'snapshots':snapshots,'baseline':baseline,'sync_generation':sync_generation,'created':time.time(),'result':result,'task_id':self.task_id}
            self.state={'status':'waiting' if snapshots else 'failed','game_id':games[0]['game_id'] if len(games)==1 else None,
                        'games':summaries,'completed':sum(s['status']!='skipped' for s in summaries),'planned':len(games),
                        'current_game':None,'token':secrets.token_urlsafe(32),'scanned':result['actual_record_count'],
                        'requests':result['request_count'],'coverage':'incomplete','report':report,'failures':errors,
                        'statistics':classify(report,result['actual_record_count'],sum(s['page_duplicates'] for s in summaries)),
                        'scan_status':'rate_limited' if any(s['scan_status']=='rate_limited' for s in summaries) else 'awaiting_resume' if errors else 'complete_check' if all(s['scan_status']=='complete_check' for s in summaries) else 'incomplete'}
            self.state['window_days']=next((s.get('window_days') for s in summaries),None)
            self.state['statistics'].update(out_of_window=sum(s.get('out_of_window',0) for s in summaries),missing_dates=sum(s.get('missing_dates',0) for s in summaries))
            excluded=self.state['statistics']['out_of_window']+self.state['statistics']['missing_dates']
            self.state['statistics']['classified']+=excluded
            self.state['statistics']['unclassified']=max(0,self.state['statistics']['unclassified']-excluded)
        self.save()

    def apply(self,only_source_changes=False,write_guard=None):
        candidate=self.candidate;c=connect_database(self.database);backup=None
        def guard(connection):
            if time.time()-candidate['created']>600 or fingerprint(connection)!=candidate['baseline']:raise ValueError('Database changed or preview expired; check again')
            if connection.execute('SELECT COALESCE(MAX(run_id),0) FROM sync_runs').fetchone()[0]!=candidate.get('sync_generation'):
                raise ValueError('Sync checkpoints changed; check again')
            if self.path.exists() and json.loads(self.path.read_text(encoding='utf-8'))['task_id']!=candidate['task_id']:
                raise ValueError('Preview replaced by another task; check again')
            if write_guard is not None:write_guard()
        def before():
            nonlocal backup
            backup=self.database.parent/'backups'/('web_sync_'+secrets.token_hex(12)+'.db');backup_database(self.database,backup)
        result=candidate['result']
        checkpoints={str(s['game_id']):{'frontier':max(s['frontier'],s['checkpoint'].get('frontier',0) if s['checkpoint'].get('per_page')==s['per_page'] else 0),'per_page':s['per_page'],
                     'pending_date_ids':s.get('pending_date_ids',[]),
                     'last_success_check_at':s['checked_at'] if s['status']=='success' else s['checkpoint'].get('last_success_check_at'),
                     'last_successful_page_at':s['checked_at'],
                     'pages':s['pages'],'known_ids':s['known_ids'],'newest_known':s['newest_known'],'coverage':s['coverage'],'failures':s['failures'],
                     'pending':s['scan_status']!='complete_check'} for s in self.state['games'] if s['pages']}
        try:
            snapshots=candidate['snapshots']
            if only_source_changes:
                selected=[]
                for meta,records in snapshots:
                    rows=[]
                    for record in records:
                        comparison=import_samples(c,[(meta,[record])],dry_run=True)
                        if comparison['inserted'] or comparison['source_update_events']:
                            rows.append(record)
                    selected.append((meta,rows))
                snapshots=selected
            preview=import_samples(c,snapshots,dry_run=True)
            report=import_samples(c,snapshots,dry_run=False,before_write=before,precondition=guard,
                sync_run={'source':'gamebanana','game_id':self.state['game_id'],'started_at':result['collected_at'],'ended_at':utc(),
                          'status':'partial' if result['failure_reasons'] else 'success','request_count':result['request_count'],
                          'fetched_count':result['actual_record_count'],'deduplicated_count':preview['unique_records'],
                          'errors':result['failure_reasons'],'web_sync':{'format':FORMAT,'task_id':candidate['task_id'],'checkpoints':checkpoints}})
        finally:c.close()
        with self.mutex:
            self.state={**self.state,'status':'partial' if result['failure_reasons'] else 'success','report':report,
                        'backup':str(backup) if backup else None,'checkpoint_committed':True}
            self.candidate=None
        try:self.save()
        except OSError as exc:
            with self.mutex:self.state['error']=f'Database committed; preview journal save failed; checkpoints recover from sync_runs: {exc}'
