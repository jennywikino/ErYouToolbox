"""Bounded author checks. Preview reports are not committed sync baselines."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import httpx
from .gamebanana import HEADERS, TIMEOUT, _retry_after_seconds
from .models import normalize_record
from .ui_queries import readonly_connection
from .importer import import_samples
from .subscriptions import verified_backup
from .content_ratings import source_ratings

FORMAT='eryoutoolbox-author-check-v1'

def baseline(connection, author):
    row=connection.execute("SELECT error_summary FROM sync_runs WHERE source='gamebanana' AND json_valid(error_summary) AND json_extract(error_summary,'$.author_check.author_id')=? ORDER BY run_id DESC LIMIT 1",(author,)).fetchone()
    return json.loads(row[0])['author_check'] if row else None

def check(database, root, *, client, resume=None, pages=1, details=5, days=30):
    if not 1<=pages<=2 or not 1<=details<=5 or not 1<=days<=30:
        raise ValueError('Use 1..2 pages, 1..5 details per author, 1..30 days')
    games=json.loads((root/'config/games.json').read_text(encoding='utf-8'))['games']
    games={g['game_id']:g for g in games}
    c=readonly_connection(database)
    try:
        authors=[dict(r) for r in c.execute("SELECT * FROM author_subscriptions WHERE source='gamebanana' ORDER BY author_id LIMIT 2")]
        old={a['author_id']:baseline(c,a['author_id']) for a in authors}
    finally:c.close()
    if resume and resume.get('format')!=FORMAT:raise ValueError('Invalid resume report')
    report={'format':FORMAT,'observed_at':datetime.now(timezone.utc).isoformat(),'authors':[], 'requests':0,'dry_run':True,'coverage':'incomplete'}
    cached={a['author_id']:a for a in (resume or {}).get('authors',[]) if a.get('status')=='success'}
    def get(url,params=None):
        if report['requests']:time.sleep(2)
        report['requests']+=1
        result['requests']=result.get('requests',0)+1
        response=client.get(url,params=params)
        if response.status_code in (403,429):
            raise SourceStop(response.status_code,response.headers.get('Retry-After'))
        response.raise_for_status()
        try:return response.json()
        except ValueError as exc:raise ValueError(f'Non-JSON response: HTTP {response.status_code}, Content-Type={response.headers.get("Content-Type")}, bytes={len(response.content)}') from exc
    for author in authors:
        aid=author['author_id']
        if aid in cached:
            report['authors'].append(cached[aid]);continue
        result={'author_id':aid,'observed_at':report['observed_at'],'records':[],'status':'success','errors':[], 'previous':old[aid], 'pages':[]}
        report['authors'].append(result)
        try:
            pending=next((a.get('pending_ids') for a in (resume or {}).get('authors',[]) if a['author_id']==aid),None)
            ids=list(pending) if pending else []
            if not pending:
                for gid in games:
                    for page in range(1,pages+1):
                        payload=get('https://api.gamebanana.com/Core/List/New',{'userid':aid,'gameid':gid, 'itemtype':'Mod','include_updated':1,'max_age':days*86400,'page':page,'format':'json'})
                        if not isinstance(payload,list):raise ValueError('Core response is not an ID array')
                        for entry in payload:
                            if not isinstance(entry,list) or len(entry)!=2 or entry[0]!='Mod' or type(entry[1]) is not int or entry[1]<=0:
                                raise ValueError('Malformed Core MOD identity')
                            if entry[1] not in ids:ids.append(entry[1])
                        result['pages'].append({'game_id':gid,'page':page,'count':len(payload),'ids':ids[:5]})
                        if not payload:break
            result['pending_ids']=list(ids)
            for item_id in ids[:details]:
                payload=get(f'https://gamebanana.com/apiv11/Mod/{item_id}/ProfilePage')
                if not isinstance(payload,dict):raise ValueError('Invalid profile object')
                game=payload.get('_aGame',{}).get('_idRow')
                observed_author=payload.get('_aSubmitter',{}).get('_idRow')
                if payload.get('_idRow')!=item_id or observed_author!=aid or game not in games:
                    raise ValueError(f'Profile identity/author/game mismatch: {item_id}')
                record=normalize_record({**payload,'_sModelName':'Mod'},games[game])
                c=readonly_connection(database)
                try:
                    row=c.execute("SELECT raw_metadata_json FROM mods WHERE source='gamebanana' AND item_type='Mod' AND item_id=?",(item_id,)).fetchone()
                    saved_rating=source_ratings(row[0]) if row else None
                    if saved_rating and saved_rating['verification']!='unverified_labels' and source_ratings({'_record':record})['verification']=='unverified_labels':
                        record['source_rating_fields']=saved_rating['raw']
                finally:c.close()
                result['records'].append(record)
                result['pending_ids'].remove(item_id)
            if len(ids)>details:
                result['status']='partial';result['errors'].append('Detail cap reached; unprocessed IDs will be retried in the next bounded scan')
        except SourceStop as exc:
            result.update(status='partial' if result['records'] else 'failed')
            result['errors'].append(str(exc));report['retry_after']=exc.retry_after
            report['rate_limited_at']=datetime.now(timezone.utc).isoformat()
            report['retry_after_seconds']=_retry_after_seconds(exc.retry_after)
            break
        except (httpx.HTTPError,ValueError,TypeError,AttributeError) as exc:
            result.update(status='partial' if result['records'] else 'failed')
            result['errors'].append(f'{type(exc).__name__}: {exc}')
    report['status']='success' if len(report['authors'])==len(authors) and all(a['status']=='success' for a in report['authors']) else 'partial' if any(a['records'] for a in report['authors']) else 'failed'
    report['records_checked']=sum(len(a['records']) for a in report['authors'])
    c=readonly_connection(database)
    try:
        for a in report['authors']:
            a['comparison']=import_samples(c,[({'captured_at':datetime.fromisoformat(report['observed_at']),'path':'author-preview'},a['records'])],dry_run=True)
            a['baseline_pending']=old[a['author_id']] is None
            a['new_publications']=sum(bool(old[a['author_id']] and r.get('created_at') and r['created_at']>old[a['author_id']]['checked_at'] and not c.execute('SELECT 1 FROM mods WHERE source=? AND item_type=? AND item_id=?',(r['source'],r['item_type'],r['item_id'])).fetchone()) for r in a['records'])
    finally:c.close()
    report['new_candidates']=sum(a['comparison']['inserted'] for a in report['authors'])
    return report

class SourceStop(Exception):
    def __init__(self,status,retry_after):
        self.retry_after=retry_after
        super().__init__(f'HTTP {status}; stopped all authors. Retry-After: {retry_after}')

def apply_report(database, report):
    if report.get('format')!=FORMAT or len(report.get('authors',[]))>2:raise ValueError('Invalid report')
    captured=datetime.fromisoformat(report['observed_at'])
    if captured.tzinfo is None:raise ValueError('UTC-aware report time required')
    results=[]
    for author in report['authors']:
        observed_at=author.get('observed_at',report['observed_at'])
        captured=datetime.fromisoformat(observed_at)
        if not author['records'] and author['status']!='success':continue
        if len(author['records'])>5:raise ValueError('Detail budget exceeded')
        c=readonly_connection(database)
        try:
            if not c.execute("SELECT 1 FROM author_subscriptions WHERE source='gamebanana' AND author_id=?",(author['author_id'],)).fetchone():continue
            old=baseline(c,author['author_id'])
        finally:c.close()
        if old and old['checked_at']>=observed_at:continue
        if any(r.get('source')!='gamebanana' or r.get('item_type')!='Mod' or r.get('author_id')!=author['author_id'] for r in author['records']):raise ValueError('Invalid author record')
        state={'author_id':author['author_id'],'baseline_at':old['baseline_at'] if old else observed_at, 'checked_at':observed_at,'coverage':'incomplete'}
        from .database import connect_database
        c=connect_database(database)
        try:
            # Baseline/run log is a real write even if all MODs are unchanged.
            result=import_samples(c,[({'captured_at':captured,'path':'author-check'},author['records'])],dry_run=False,
                before_write=lambda:verified_backup(database),sync_run={'source':'gamebanana','game_id':None,'started_at':report['observed_at'],
                  'ended_at':report['observed_at'],'status':'success','author_check':state,
                  'request_count':author.get('requests',0),'fetched_count':len(author['records']),'deduplicated_count':len(author['records'])})
            result['new_publications']=author.get('new_publications',0)
            results.append(result)
        finally:c.close()
    return results

def save_report(root,report):
    directory=root/'logs/author_updates';directory.mkdir(parents=True,exist_ok=True)
    path=directory/('check_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')+'.json')
    with path.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    temp=directory/'latest.tmp';temp.write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8');temp.replace(directory/'latest.json')
    return path

def preview(database,root,resume=None,pages=1,details=5):
    # Same OS lock primitive as bounded backfills, isolated from rating jobs.
    import sys
    sys.path.insert(0,str(root/'scripts'))
    from backfill_content_ratings import instance_lock
    with instance_lock(root/'logs/author_updates/instance.lock'):
        latest=root/'logs/author_updates/latest.json'
        if latest.exists():
            previous=json.loads(latest.read_text(encoding='utf-8'))
            if previous.get('retry_after_seconds') is not None:
                elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(previous.get('rate_limited_at',previous['observed_at']))).total_seconds()
                if elapsed<previous['retry_after_seconds']:raise ValueError('Retry-After is still active')
        with httpx.Client(timeout=TIMEOUT,headers=HEADERS) as client:
            report=check(database,root,client=client,resume=resume,pages=pages,details=details)
        return report,save_report(root,report)
