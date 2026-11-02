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

def check(database, root, *, client, resume=None, pages=1, details=5, days=30, author_ids=None):
    if not 1<=pages<=2 or not 1<=details<=5 or not 1<=days<=30:
        raise ValueError('Use 1..2 pages, 1..5 details per author, 1..30 days')
    games=json.loads((root/'config/games.json').read_text(encoding='utf-8'))['games']
    games={g['game_id']:g for g in games}
    c=readonly_connection(database)
    try:
        authors=[dict(r) for r in c.execute("SELECT * FROM author_subscriptions WHERE source='gamebanana' ORDER BY author_id")]
        authors=[a for a in authors if author_ids is None or a['author_id'] in author_ids][:2]
        if author_ids is not None:authors.sort(key=lambda a:author_ids.index(a['author_id']))
        old={a['author_id']:baseline(c,a['author_id']) for a in authors}
    finally:c.close()
    if resume and resume.get('format')!=FORMAT:raise ValueError('Invalid resume report')
    report={'format':FORMAT,'observed_at':datetime.now(timezone.utc).isoformat(),'authors':[], 'requests':0,'dry_run':True,'coverage':'incomplete','request_budget':2*(len(games)*pages+details)}
    cached={a['author_id']:a for a in (resume or {}).get('authors',[]) if a.get('status')=='success'}
    def get(url,params=None):
        if report['requests']:time.sleep(2)
        if report['requests']>=report['request_budget']:raise ValueError('Author request budget exhausted')
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
            committed=old[aid] or {}
            ids=list(pending or committed.get('pending_ids',[]))
            result['pending_ids']=ids
            result['list_complete']=bool(committed.get('list_complete') and ids)
            if pending:result['list_complete']=next((a.get('list_complete',False) for a in (resume or {}).get('authors',[]) if a['author_id']==aid),False)
            if not result['list_complete']:
                for gid in games:
                    for page in range(1,pages+1):
                        payload=get('https://api.gamebanana.com/Core/List/New',{'userid':aid,'gameid':gid, 'itemtype':'Mod','include_updated':1,'max_age':days*86400,'page':page,'format':'json'})
                        if not isinstance(payload,list):raise ValueError('Core response is not an ID array')
                        if len(payload)>500:raise ValueError('Core ID response exceeds bounded sample size')
                        for entry in payload:
                            if not isinstance(entry,list) or len(entry)!=2 or entry[0]!='Mod' or type(entry[1]) is not int or entry[1]<=0:
                                raise ValueError('Malformed Core MOD identity')
                            if entry[1] not in ids and entry[1] not in (committed.get('done_ids',[]) if committed.get('pending_ids') or not committed.get('checked_at') else []):ids.append(entry[1])
                        result['pages'].append({'game_id':gid,'page':page,'count':len(payload),'ids':ids[:5]})
                        if not payload:break
                result['list_complete']=True
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
                    row=c.execute("SELECT raw_metadata_json,preview_urls_json,content_rating_status FROM mods WHERE source='gamebanana' AND item_type='Mod' AND item_id=?",(item_id,)).fetchone()
                    if row:
                        if row['preview_urls_json']:record['preview_images']=json.loads(row['preview_urls_json'])
                        record['content_rating_status']=row['content_rating_status']
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
            if report['retry_after_seconds'] is not None:time.sleep(report['retry_after_seconds'])
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
            a['new_publications']=sum(bool(old[a['author_id']] and r.get('created_at') and r['created_at']>(old[a['author_id']].get('checked_at') or old[a['author_id']]['baseline_at']) and not c.execute('SELECT 1 FROM mods WHERE source=? AND item_type=? AND item_id=?',(r['source'],r['item_type'],r['item_id'])).fetchone()) for r in a['records'])
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
        if old and old.get('checked_at') and old['checked_at']>=observed_at:continue
        if any(r.get('source')!='gamebanana' or r.get('item_type')!='Mod' or r.get('author_id')!=author['author_id'] for r in author['records']):raise ValueError('Invalid author record')
        state={'author_id':author['author_id'],'baseline_at':old['baseline_at'] if old else observed_at,
               'checked_at':observed_at if author['status']=='success' else (old or {}).get('checked_at'),
               'pending_ids':author.get('pending_ids',[]),'list_complete':author.get('list_complete',False),
               'done_ids':list(dict.fromkeys((old or {}).get('done_ids',[])+[r['item_id'] for r in author['records']]))[-1000:],
               'initial':old is None,'coverage':'incomplete'}
        from .database import connect_database
        c=connect_database(database)
        try:
            def guard(connection):
                if not connection.execute("SELECT 1 FROM author_subscriptions WHERE source='gamebanana' AND author_id=?",(author['author_id'],)).fetchone():
                    raise ValueError('Author was unfollowed; report not applied')
                if baseline(connection,author['author_id'])!=old:raise ValueError('Author baseline changed; check again')
            # Baseline/run log is a real write even if all MODs are unchanged.
            result=import_samples(c,[({'captured_at':captured,'path':'author-check'},author['records'])],dry_run=False,
                before_write=lambda:verified_backup(database),precondition=guard,sync_run={'source':'gamebanana','game_id':None,'started_at':report['observed_at'],
                  'ended_at':report['observed_at'],'status':author['status'],'author_check':state,
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
    with instance_lock(root/'logs/content_ratings/instance.lock'):
        latest=root/'logs/author_updates/latest.json'
        if latest.exists():
            previous=json.loads(latest.read_text(encoding='utf-8'))
            if previous.get('rate_limited_at'):
                elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(previous.get('rate_limited_at',previous['observed_at']))).total_seconds()
                if elapsed<(previous.get('retry_after_seconds') or 21600):raise ValueError('Retry-After is still active')
        with httpx.Client(timeout=TIMEOUT,headers=HEADERS) as client:
            report=run_rotation(database,root,client=client,advance=False,resume=resume,pages=pages,details=details)
        return report,save_report(root,report)


def run_rotation(database,root,*,client,apply=False,advance=True,write_guard=None,**options):
    """Caller owns the shared content_ratings/instance.lock; never acquire it twice."""
    directory=Path(root)/'logs/author_updates';path=directory/'rotation.json'
    state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'format':FORMAT,'cursor':0,'failures':{}}
    if state.get('format')!=FORMAT:raise ValueError('Invalid rotation state; retained')
    if time.time()<state.get('not_before',0):raise ValueError('Author source cooldown active')
    c=readonly_connection(database)
    try:ids=[r[0] for r in c.execute("SELECT author_id FROM author_subscriptions WHERE source='gamebanana' ORDER BY author_id")]
    finally:c.close()
    queue=[a for a in ids if a>state['cursor']]+[a for a in ids if a<=state['cursor']]
    selected=[a for a in queue if state['failures'].get(str(a),{}).get('not_before',0)<=time.time()][:2]
    if options.get('resume') is None:
        options['resume']={'format':FORMAT,'authors':[{'author_id':a,'status':'failed',**state['failures'][str(a)]} for a in selected if str(a) in state['failures']]}
    report=(check(database,Path(root),client=client,author_ids=selected,**options) if selected else
            {'format':FORMAT,'observed_at':datetime.now(timezone.utc).isoformat(),'authors':[],
             'requests':0,'status':'success','dry_run':True,'coverage':'incomplete'})
    report['followed_count']=len(ids);report['checked_authors']=len(report['authors']);report['applied']=[]
    for author in report['authors']:
        aid=author['author_id'];key=str(aid)
        if apply:
            try:
                if write_guard:write_guard()
                report['applied'].extend(apply_report(database,{**report,'authors':[author]}))
            except Exception as exc:
                author['status']='failed';author['errors'].append(f'Apply failed: {exc}')
        if advance:
            state['cursor']=aid
            if author['status']=='success':state['failures'].pop(key,None)
            else:
                cap_only=author['status']=='partial' and author['errors']==['Detail cap reached; unprocessed IDs will be retried in the next bounded scan']
                tries=0 if cap_only else state['failures'].get(key,{}).get('attempts',0)+1
                state['failures'][key]={'attempts':min(tries,2),'pending_ids':author.get('pending_ids',[]),
                    'errors':author['errors'],'list_complete':author.get('list_complete',False),
                    'not_before':time.time()+21600 if tries>=2 else 0}
                if not apply or author['status']=='failed':
                    state['failures'][key]['pending_ids']=list(dict.fromkeys([r['item_id'] for r in author['records']]+author.get('pending_ids',[])))
    state['failures']={k:v for k,v in state['failures'].items() if int(k) in ids}
    report['status']='success' if all(a['status']=='success' for a in report['authors']) else 'partial' if any(a['status']!='failed' for a in report['authors']) else 'failed'
    if report.get('rate_limited_at'):
        state['not_before']=time.time()+max(report.get('retry_after_seconds') or 21600,1)
    report['pending_count']=sum(len(a.get('pending_ids',[])) for a in report['authors'])
    save_report(Path(root),report)
    if advance:
        directory.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    return report
