"""Read-only, bounded online rankings. No SQLite imports or mutations."""
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
import time
import httpx
from .gamebanana import API_URL, HEADERS, TIMEOUT, inspect_pagination, _retry_after_seconds
from .models import normalize_record
from .content_ratings import source_ratings
from .ui_queries import readonly_connection

SORTS={'likes':'Generic_MostLiked','views':'Generic_MostViewed','downloads':'Generic_MostDownloaded'}

class PopularClient:
    def __init__(self, client=None, clock=time.monotonic):
        self.client=client;self.clock=clock;self.cache={};self.lock=Lock();self.pause_until=0;self.last_request=None
        self.recent_cache={};self.board_cache={};self.recent_lock=Lock()
    def fetch(self,game,sort='likes',page=1,limit=20,refresh=False,*,_newest=False):
        if sort not in SORTS or type(page) is not int or not 1<=page<=100 or type(limit) is not int or not 1<=limit<=(50 if _newest else 20):
            raise ValueError('Invalid ranking sort, page or limit')
        key=(game['game_id'],'newest' if _newest else sort,page,limit)
        with self.lock:
            if self.clock()<self.pause_until:raise RuntimeError('Source cooldown active; retry later')
            if not refresh and key in self.cache and self.clock()-self.cache[key][0]<1800:
                result=deepcopy(self.cache[key][1]);result['cached']=True;return result
            if self.last_request is not None:
                time.sleep(max(0,2-(self.clock()-self.last_request)))
            owned=self.client is None
            client=self.client or httpx.Client(timeout=TIMEOUT,headers=HEADERS)
            try:
                self.last_request=self.clock()
                response=client.get(API_URL,params={'_nPage':page,'_nPerpage':limit,'_aFilters[Generic_Game]':game['game_id'],'_sSort':'Generic_Newest' if _newest else SORTS[sort]})
                if response.status_code in (403,429):
                    wait=_retry_after_seconds(response.headers.get('Retry-After'))
                    self.pause_until=self.clock()+(wait if wait is not None else 1800)
                    raise RuntimeError(f"HTTP {response.status_code}; stopped. Retry-After: {response.headers.get('Retry-After')}")
                response.raise_for_status()
                payload=response.json()
                if not isinstance(payload,dict) or not isinstance(payload.get('_aRecords'),list):raise ValueError('Invalid ranking JSON structure')
                rows=payload['_aRecords'];metadata=payload.get('_aMetadata')
                if not isinstance(metadata,dict) or '_nPerpage' not in metadata:raise ValueError('Missing source pagination metadata')
                pagination=inspect_pagination(limit,page,len(rows),metadata)
                if pagination.get('error'):raise ValueError(pagination['error'])
                items=[]
                for index,row in enumerate(rows):
                    if not isinstance(row,dict) or not isinstance(row.get('_aGame'),dict) or row['_aGame'].get('_idRow')!=game['game_id'] or row.get('_sModelName')!='Mod':raise ValueError('Ranking game/type mismatch')
                    item=normalize_record(row,game)
                    if not item['item_id']:raise ValueError('Missing MOD ID')
                    item['rank']=(page-1)*(pagination['metadata_per_page'] or limit)+index+1
                    item['source_ratings']=source_ratings(row)
                    item['metrics']={label:row[key] for label,key in (('likes','_nLikeCount'),('views','_nViewCount')) if type(row.get(key)) is int and row[key]>=0}
                    item['image_count']=len(item['preview_images']);items.append(item)
                result={'items':items,'sort':sort,'page':page,'limit':limit,'metadata':metadata,
                        'has_more':not pagination.get('end_of_results') and bool(rows),
                        'fetched_at':datetime.now(timezone.utc).isoformat(),'cached':False}
                if len(self.cache)>=64:self.cache.pop(next(iter(self.cache)))
                self.cache[key]=(self.clock(),deepcopy(result))
                return result
            except ValueError as exc:
                raise RuntimeError(f'Invalid ranking response: {exc}') from exc
            finally:
                if owned:client.close()

    def recent(self,game,sort='likes',*,days=30,page=1,limit=20,max_pages=2,per_page=50,refresh=False,now=None):
        if (sort not in SORTS or days not in (7,30,90) or type(page) is not int or not 1<=page<=100
                or not 1<=limit<=20 or not 1<=max_pages<=5 or not 1<=per_page<=50):
            raise ValueError('Invalid recent window, metric or bounded paging settings')
        key=(game['game_id'],days,max_pages,per_page)
        with self.recent_lock:
            cached=not refresh and key in self.recent_cache and self.clock()-self.recent_cache[key][0]<1800
            if cached:
                base=deepcopy(self.recent_cache[key][1])
            else:
                stamp=now or datetime.now(timezone.utc).timestamp()
                cutoff=stamp-days*86400
                records={};seen=set();source_times=[];fetched=0;duplicates=0;missing=0;previous=None;ordered=True;boundary=False;errors=[];pages=0
                for number in range(1,max_pages+1):
                    try:batch=self.fetch(game,page=number,limit=per_page,refresh=refresh,_newest=True)
                    except (httpx.HTTPError,RuntimeError,ValueError) as exc:
                        errors.append(f'{type(exc).__name__}: {exc}');break
                    pages+=1
                    source_times.append(batch['fetched_at'])
                    for item in batch['items']:
                        fetched+=1
                        identity=(item['source'],item['item_type'],item['item_id'])
                        if identity in seen:duplicates+=1
                        seen.add(identity)
                        ts=item.get('created_at_timestamp')
                        if type(ts) is not int or ts>stamp:
                            missing+=1;continue
                        if previous is not None and ts>previous:ordered=False
                        previous=ts
                        if ts<cutoff:boundary=True;continue
                        # Only real creation timestamps select recent candidates.
                        records.setdefault(identity,item)
                    if boundary and ordered and not missing and not duplicates:break
                    if not batch['has_more']:break
                base={'items':list(records.values()),'fetched_at':min(source_times) if source_times else datetime.fromtimestamp(stamp,timezone.utc).isoformat(),
                      'coverage':'boundary_observed' if boundary and ordered and not missing and not duplicates and not errors else 'incomplete',
                      'boundary_observed':boundary,'cutoff':datetime.fromtimestamp(cutoff,timezone.utc).isoformat(),
                      'pages_scanned':pages,'raw_count':fetched,'duplicates':duplicates,'missing_times':missing,
                      'time_order_valid':ordered,'errors':errors,'status':'partial' if errors else 'success'}
                if errors and not pages:raise RuntimeError(errors[0])
                if len(self.recent_cache)>=32:self.recent_cache.pop(next(iter(self.recent_cache)))
                self.recent_cache[key]=(self.clock(),deepcopy(base))
            board_key=(*key,sort,page,limit,base['fetched_at'])
            if cached and board_key in self.board_cache:
                result=deepcopy(self.board_cache[board_key]);result['cached']=True;return result
            candidates=[item for item in base['items'] if sort in item['metrics']]
            candidates.sort(key=lambda item:(-item['metrics'][sort],-item['created_at_timestamp'],item['item_id']))
            for index,item in enumerate(candidates):item['rank']=index+1;item['ranking_scope']='recent_sample'
            result={**base,'items':candidates[(page-1)*limit:page*limit], 'candidate_count':len(base['items']),
                    'missing_metrics':len(base['items'])-len(candidates),'total_ranked':len(candidates),
                    'sort':sort,'days':days,'page':page,'limit':limit,'cached':cached,
                    'has_more':page*limit<len(candidates),'ranking_scope':'recent_sample'}
            if len(self.board_cache)>=64:self.board_cache.pop(next(iter(self.board_cache)))
            self.board_cache[board_key]=deepcopy(result)
            return result

def link_local(database,result):
    result=deepcopy(result)
    c=readonly_connection(database)
    try:
        ids=[item['item_id'] for item in result['items']]
        known=set()
        evidence={}
        if ids:
            known={r[0] for r in c.execute("SELECT item_id FROM mods WHERE source='gamebanana' AND item_type='Mod' AND item_id IN ("+','.join('?' for _ in ids)+')',ids)}
            from .content_ratings import source_ratings
            evidence={r[0]:source_ratings(r[1]) for r in c.execute("SELECT item_id,raw_metadata_json FROM mods WHERE source='gamebanana' AND item_type='Mod' AND item_id IN ("+','.join('?' for _ in ids)+')',ids)}
        for item in result['items']:
            item['is_local']=item['item_id'] in known
            saved=evidence.get(item['item_id'])
            # A list flag must not erase concrete, verified local detail labels.
            if saved and saved['verification']=='explicit_labels' and item.get('source_ratings',{}).get('verification')!='explicit_labels':
                item['source_ratings']=saved
    finally:c.close()
    return result
