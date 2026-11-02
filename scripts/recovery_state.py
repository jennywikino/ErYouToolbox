"""Explicit portable recovery-state allowlist; caches and process state excluded."""
import hashlib
import json
import math
import uuid

PATHS = (
    'config/project_identity.json',
    'logs/author_updates/rotation.json', 'logs/author_updates/latest.json',
    'logs/history_sync/state.json', 'logs/history_sync/settings.json', 'logs/history_sync/cooldown.json',
    'logs/preview_repairs/state.json', 'logs/preview_repairs/cooldown.json',
    'logs/web_sync/task.json',
)


def suffix(path):
    return next((name for name in PATHS if path.as_posix().endswith('/'+name)), None)


def validate(path, value):
    name = suffix(path)
    if not name: return False
    if not isinstance(value,dict): raise ValueError('Recovery state must be an object')
    def require(ok):
        if not ok: raise ValueError('Invalid recovery state: '+name)
    def ids(items):return isinstance(items,list) and all(type(i) is int and i>0 for i in items)
    def number(n):return type(n) in (int,float) and math.isfinite(n) and n>=0
    if name=='config/project_identity.json':
        require({'project_id'}<=set(value)<= {'project_id','name'});uuid.UUID(value['project_id'])
    elif name.endswith('/cooldown.json'):
        require(set(value)<= {'not_before','http_status','observed_at'} and number(value.get('not_before')))
    elif name=='logs/history_sync/settings.json':
        require(set(value)=={'enabled','paused','max_pages'} and type(value['enabled']) is bool and type(value['paused']) is bool and type(value['max_pages']) is int and 1<=value['max_pages']<=5)
    elif name=='logs/author_updates/rotation.json':
        require(value.get('format')=='eryoutoolbox-author-check-v1' and type(value.get('cursor')) is int and value['cursor']>=0 and isinstance(value.get('failures'),dict))
        for key,item in value['failures'].items():
            require(key.isdecimal() and int(key)>0 and isinstance(item,dict) and ids(item.get('pending_ids',[])) and number(item.get('not_before',0)))
    elif name=='logs/author_updates/latest.json':
        require(value.get('format')=='eryoutoolbox-author-check-v1' and isinstance(value.get('authors'),list) and len(value['authors'])<=2 and isinstance(value.get('observed_at'),str))
        for item in value['authors']:
            require(isinstance(item,dict) and type(item.get('author_id')) is int and item['author_id']>0 and ids(item.get('pending_ids',[])))
    elif name=='logs/history_sync/state.json':
        require(value.get('format')=='eryoutoolbox-history-v1' and value.get('database')=='data/eryoutoolbox.db' and isinstance(value.get('games'),dict))
        for key,item in value['games'].items():require(key.isdecimal() and int(key)>0 and isinstance(item,dict) and number(item.get('last_attempt_epoch',0)))
    elif name=='logs/preview_repairs/state.json':
        require(value.get('format')=='preview-repairs-v1' and value.get('database')=='data/eryoutoolbox.db' and isinstance(value.get('items'),dict))
        for key,item in value['items'].items():
            require(key.isdecimal() and int(key)>0 and isinstance(item,dict) and item.get('status') in ('verified','failed','source_no_images') and number(item.get('checked_at')) and number(item.get('next_check')))
    elif name=='logs/web_sync/task.json':
        require(value.get('format')=='eryoutoolbox-web-sync-v1' and value.get('database')=='data/eryoutoolbox.db' and isinstance(value.get('state'),dict) and isinstance(value.get('task_id'),str))
        require(value['state'].get('status') not in ('checking','importing'))
        require(value.get('candidate') is None or isinstance(value['candidate'],dict))
    return True


def database_digest(connection):
    """All user tables + schema; includes personal states and every sync cursor."""
    tables=[]
    for name,sql in connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        quoted=name.replace('"','""')
        rows=sorted(json.dumps(tuple(r),ensure_ascii=False,default=lambda b:b.hex()) for r in connection.execute(f'SELECT * FROM "{quoted}"'))
        tables.append((name,sql,rows))
    return hashlib.sha256(json.dumps(tables,ensure_ascii=False).encode()).hexdigest()


def coherence(connection, states):
    task=states.get('logs/web_sync/task.json')
    if task and task.get('candidate'):
        candidate=task['candidate']
        rows=[tuple(r) for r in connection.execute('SELECT * FROM mods ORDER BY source,item_type,item_id')]
        baseline=hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()
        generation=connection.execute('SELECT COALESCE(MAX(run_id),0) FROM sync_runs').fetchone()[0]
        if candidate.get('baseline')!=baseline or candidate.get('sync_generation')!=generation or candidate.get('task_id')!=task['task_id']:
            raise ValueError('Web preview/database mismatch; discard through the existing UI before backup')
    history=states.get('logs/history_sync/state.json',{})
    checkpoints={}
    for row in connection.execute("SELECT game_id,error_summary FROM sync_runs WHERE json_valid(error_summary) ORDER BY run_id DESC"):
        data=json.loads(row[1]).get('history_scan',{})
        if data:checkpoints.setdefault(str(row[0]),data.get('checkpoint'))
    for game,item in history.get('games',{}).items():
        if item.get('status')=='checking':raise ValueError('Historical scan is still running; pause writers')
        if item.get('checkpoint') and item['checkpoint']!=checkpoints.get(game):raise ValueError('History mirror/database checkpoint mismatch')
    repairs=states.get('logs/preview_repairs/state.json',{})
    for item_id,item in repairs.get('items',{}).items():
        if item['status']=='verified':
            row=connection.execute("SELECT preview_urls_json FROM mods WHERE source='gamebanana' AND item_type='Mod' AND item_id=?",(int(item_id),)).fetchone()
            if not row or not json.loads(row[0] or '[]'):raise ValueError('Verified preview checkpoint/database mismatch')
