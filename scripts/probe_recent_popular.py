"""One game, one Newest page, five records; read-only sample validation."""
import sys,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from eryoutoolbox.popular import PopularClient,link_local
if __name__=='__main__':
    database=ROOT/'data/eryoutoolbox.db';before=hashlib.sha256(database.read_bytes()).hexdigest()
    game=next(g for g in json.loads((ROOT/'config/games.json').read_text(encoding='utf-8'))['games'] if g['game_id']==8552)
    try:
        result=link_local(database,PopularClient().recent(game,days=30,max_pages=1,per_page=5))
        result['items']=[{k:i.get(k) for k in ('item_id','created_at','rank','metrics','is_local')} for i in result['items']]
    except Exception as exc:result={'status':'failed','error':str(exc)}
    result['database_unchanged']=before==hashlib.sha256(database.read_bytes()).hexdigest()
    path=ROOT/'logs'/('recent_popular_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')+'.json')
    path.parent.mkdir(exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=True,indent=2));print('Report:',path)
    raise SystemExit(int(result['status']=='failed'))
