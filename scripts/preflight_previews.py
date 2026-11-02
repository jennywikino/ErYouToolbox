"""Six-game preview preflight. Production connections are read-only; never apply."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from repair_previews import audit,repair,open_existing_database,GAMES
from auto_sync import atomic_json


def digest(database):
    c=open_existing_database(database)
    try:
        c.execute('BEGIN');tables={}
        for table in ('mods','user_states','author_subscriptions','mod_events','sync_runs'):
            tables[table]=[tuple(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY rowid')]
        return hashlib.sha256(json.dumps(tables,ensure_ascii=False).encode()).hexdigest()
    finally:c.close()


def preflight(root,*,online=False,runner=repair):
    root=Path(root);db=root/'data/eryoutoolbox.db';before=digest(db)
    state_path=root/'logs/preview_repairs/state.json'
    state_before=state_path.read_bytes() if state_path.exists() else None
    state=json.loads(state_before) if state_before else {'items':{}}
    if state_before and (state.get('format')!='preview-repairs-v1' or state.get('database')!='data/eryoutoolbox.db'):raise ValueError('Repair state identity mismatch')
    backups=lambda:sorted((p.name,p.stat().st_size) for p in (root/'data/backups').glob('*.db'))
    backups_before=backups();report={'checked_at':time.time(),'online':online,'audit':audit(db),'games':[],'requests':0}
    for g in report['audit']['games']:
        missing=set(g['ids']['missing']+g['ids']['thumbnail_or_unverified'])
        local=set().union(*(set(g['ids'][k]) for k in ('missing','thumbnail_or_unverified','original_metadata')))
        g['counts']['total']=len(local)
        for label,status in [('repair_success','verified'),('repair_failed','failed'),('source_no_images','source_no_images')]:
            ids=[int(i) for i,v in state['items'].items() if int(i) in local and v['status']==status]
            g['ids'][label]=ids;g['counts'][label]=len(ids)
        g['ids']['pending']=sorted(missing-set(g['ids']['source_no_images']));g['counts']['pending']=len(g['ids']['pending'])
    if online:
        for game in GAMES:
            if report['requests']>=60:break
            result=runner(root,db,game,limit=min(10,60-report['requests']),apply=False)
            report['requests']+=result.get('requests',0)
            result['skipped_after_parsing']=sorted(set(result.get('obtained_images',[]))-set(result.get('to_update',[])))
            report['games'].append(result)
            atomic_json(root/'logs/preview_repairs/preflight_running.json',report)
            if result['status']=='cooldown' or any(f.get('http_status') in (403,429) for f in result.get('failed',[])):break
    report['unexecuted_games']=[g['game_id'] for g in GAMES if not any(r.get('game',{}).get('game_id')==g['game_id'] for r in report['games'])] if online else []
    report['business_data_unchanged']=before==digest(db)
    report['repair_state_unchanged']=state_before==(state_path.read_bytes() if state_path.exists() else None)
    report['backups_unchanged']=backups_before==backups()
    c=open_existing_database(db)
    try:
        ids=[436225,475764,487517,502646,502722,502886,502891,506347,515521,539510]
        report['previous_ten']=[{'item_id':i,'has_original_metadata':any(i in g['ids']['original_metadata'] for g in report['audit']['games']),'state':state['items'].get(str(i))} for i in ids]
    finally:c.close()
    report['status']='pass' if report['business_data_unchanged'] and report['repair_state_unchanged'] and report['backups_unchanged'] else 'changed_during_preflight'
    output=root/'logs/preview_repairs'/('preflight_'+str(time.time_ns())+'.json');atomic_json(output,report)
    return report,output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--online',action='store_true');args=parser.parse_args()
    report,output=preflight(ROOT,online=args.online)
    print(json.dumps({'report':str(output),'status':report['status'],'requests':report['requests'],
        'statistics':[{**{k:v for k,v in g.items() if k!='ids'}} for g in report['audit']['games']],
        'results':[{k:v for k,v in r.items() if k!='game'}|{'game':r.get('game')} for r in report['games']]},ensure_ascii=False,indent=2))
