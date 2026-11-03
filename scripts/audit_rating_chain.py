"""Read-only local/source rating audit. Online mode makes at most 12 detail requests."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eryoutoolbox.content_ratings import source_ratings
from eryoutoolbox.ui_queries import readonly_connection, query_mod_detail
from backfill_content_ratings import fetch_batch
from eryoutoolbox.gamebanana import HEADERS,TIMEOUT


def audit(database):
    c=readonly_connection(database)
    try:
        rows=c.execute("SELECT source,item_type,item_id,game_id,first_seen_at,raw_metadata_json FROM mods ORDER BY first_seen_at DESC,item_id DESC").fetchall()
    finally:c.close()
    games=json.loads((ROOT/'config/games.json').read_text(encoding='utf-8'))['games']
    result={'database':str(Path(database).resolve()),'total':len(rows),'states':Counter(),'codes':Counter(),'games':{},'ids':{},'recent':[]}
    for game in games:
        result['games'][str(game['game_id'])]={'name':game['name'],'total':0,'states':Counter(),'codes':Counter()}
    for row in rows:
        rating=source_ratings(row['raw_metadata_json'])
        state=rating['verification'];result['states'][state]+=1;result['codes'].update(rating['codes'])
        result['ids'].setdefault(state,[]).append(row['item_id'])
        entry=result['games'].get(str(row['game_id']))
        if entry:
            entry['total']+=1;entry['states'][state]+=1;entry['codes'].update(rating['codes'])
        if len(result['recent'])<12:
            result['recent'].append({'item_id':row['item_id'],'game_id':row['game_id'],'first_seen_at':row['first_seen_at'],'rating':rating})
    for entry in result['games'].values():
        entry['verified_fraction']=(entry['total']-entry['states']['unverified_labels'])/entry['total'] if entry['total'] else None
    return result,rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',type=Path,action='append',required=True)
    p.add_argument('--online',action='store_true')
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    before={str(d):hashlib.sha256(d.read_bytes()).hexdigest() for d in args.database}
    result={'observed_at':datetime.now(timezone.utc).isoformat(),'databases':[],'requests':0,'samples':[]}
    local={};selected=[]
    for database in args.database:
        report,rows=audit(database);result['databases'].append(report)
        for row in rows:
            if row['source']=='gamebanana' and row['item_type']=='Mod':local.setdefault(row['item_id'],[]).append((database,row))
        for state in ('explicit_labels','source_unrated_flag','unverified_labels'):
            selected.extend(report['ids'].get(state,[])[:2])
        selected.extend([r['item_id'] for r in report['recent'][:4]])
    selected=list(dict.fromkeys(i for i in selected if i in local))[:12]
    result['selected_ids']=selected
    if args.online:
        with httpx.Client(timeout=TIMEOUT,headers=HEADERS) as client:
            source=fetch_batch(client,selected,delay=2)
        result['requests']=source['requests'];result['failures']=source['failures']
        for sample in source['samples']:
            item_id=sample['item_id']
            entry={'item_id':item_id,'source_fields':sample['detail'],'source_rating':source_ratings(sample['detail']),'local':[]}
            for database,row in local[item_id]:
                raw=json.loads(row['raw_metadata_json'] or '{}')
                normalized=raw.get('_record',{})
                api_item=query_mod_detail(database,source='gamebanana',item_type='Mod',item_id=item_id)
                entry['local'].append({'database':str(database),'rating':source_ratings(raw),'list_rating_fields':normalized.get('source_rating_fields'),
                    'has_content_ratings':normalized.get('has_content_ratings'),'has_saved_detail_evidence':'_source_rating_evidence' in raw,
                    'api_rating':api_item['source_ratings']})
            result['samples'].append(entry)
    result['database_unchanged']={str(d):hashlib.sha256(d.read_bytes()).hexdigest()==before[str(d)] for d in args.database}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('databases','samples')},ensure_ascii=True))
    for d in result['databases']:print(json.dumps({k:v for k,v in d.items() if k not in ('ids','recent')},ensure_ascii=True))


if __name__=='__main__':main()
