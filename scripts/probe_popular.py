"""One small, read-only source ranking request; no image/file downloads."""
import json,sys,hashlib
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from eryoutoolbox.popular import PopularClient,link_local

def main():
    database=ROOT/'data/eryoutoolbox.db'
    before=hashlib.sha256(database.read_bytes()).hexdigest()
    game=next(g for g in json.loads((ROOT/'config/games.json').read_text(encoding='utf-8'))['games'] if g['game_id']==8552)
    try:
        data=link_local(database,PopularClient().fetch(game,'likes',page=1,limit=3))
        report={'status':'success','requests':1,'sort':'Generic_MostLiked','game_id':8552,'page':1,
                'fetched_at':data['fetched_at'],'metadata':data['metadata'],
                'items':[{k:i[k] for k in ('item_id','game_id','rank','metrics','is_local','source_ratings')} for i in data['items']]}
    except Exception as exc:report={'status':'failed','error':f'{type(exc).__name__}: {exc}'}
    report['database_unchanged']=before==hashlib.sha256(database.read_bytes()).hexdigest()
    path=ROOT/'logs'/('popular_probe_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')+'.json')
    path.parent.mkdir(exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=True,indent=2));print('Report:',path)
    return int(report['status']=='failed')
if __name__=='__main__':raise SystemExit(main())
