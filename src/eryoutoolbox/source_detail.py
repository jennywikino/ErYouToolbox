"""Explicit read-only source detail, bounded cache, no import or media downloads."""
from copy import deepcopy
from datetime import datetime,timezone
from html.parser import HTMLParser
import threading
import time
import httpx
from .gamebanana import HEADERS,TIMEOUT,_retry_after_seconds
from .models import normalize_record
from .content_ratings import source_ratings


class PlainText(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
        if tag in ('p','br','li','div','h1','h2','h3'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
        if tag in ('p','li','div'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


def summary(record):
    metrics={label:record[key] for label,key in [('likes','_nLikeCount'),('views','_nViewCount'),('downloads','_nDownloadCount'),('comments','_nPostCount')]
             if type(record.get(key)) is int and record[key]>=0}
    parser=PlainText();parser.feed(record.get('_sText','') if isinstance(record.get('_sText'),str) else '')
    files=[]
    for f in record.get('_aFiles',[]) if isinstance(record.get('_aFiles'),list) else []:
        if not isinstance(f,dict) or not isinstance(f.get('_sFile'),str):continue
        entry={'name':f['_sFile'][:300]}
        for source,target in [('_tsDateAdded','uploaded_at_timestamp'),('_nDownloadCount','downloads')]:
            if type(f.get(source)) is int and f[source]>=0:entry[target]=f[source]
        files.append(entry)
    return {'metrics':metrics,'files':files[:100], 'file_count':len(files) if isinstance(record.get('_aFiles'),list) else None,
            'description':''.join(parser.parts).strip() or None}


class SourceDetail:
    def __init__(self,client=None,clock=time.monotonic):
        self.client=client;self.clock=clock;self.lock=threading.Lock();self.cache={};self.pause_until=0;self.last=None
    def fetch(self,item_id,game):
        if type(item_id) is not int or item_id<=0:raise ValueError('Invalid MOD ID')
        key=(item_id,game['game_id'])
        with self.lock:
            now=self.clock()
            if key in self.cache and now-self.cache[key][0]<1800:return deepcopy(self.cache[key][1])
            if now<self.pause_until:raise RuntimeError('Source detail cooldown; retry later')
            if self.last is not None:time.sleep(max(0,2-(now-self.last)))
            owned=self.client is None;client=self.client or httpx.Client(timeout=TIMEOUT,headers=HEADERS)
            try:
                self.last=self.clock();r=client.get(f'https://gamebanana.com/apiv11/Mod/{item_id}/ProfilePage')
                if r.status_code in (403,429):
                    self.pause_until=self.clock()+max(_retry_after_seconds(r.headers.get('Retry-After')) or 1800,1)
                    raise RuntimeError(f'HTTP {r.status_code}; stopped; Retry-After={r.headers.get("Retry-After")}')
                r.raise_for_status();record=r.json()
                if (not isinstance(record,dict) or type(record.get('_idRow')) is not int or record['_idRow']!=item_id
                    or record.get('_sProfileUrl')!=f'https://gamebanana.com/mods/{item_id}'
                    or not isinstance(record.get('_aGame'),dict) or record['_aGame'].get('_idRow')!=game['game_id']):raise ValueError('Source detail identity/game mismatch')
                item=normalize_record({**record,'_sModelName':'Mod'},game)
                item.update(summary(record),source_ratings=source_ratings(record),is_local=False,image_count=len(item['preview_images']),
                            fetched_at=datetime.now(timezone.utc).isoformat())
                item['category']=record.get('_aSuperCategory',{}).get('_sName') if isinstance(record.get('_aSuperCategory'),dict) else None
                item['subcategory']=record.get('_aCategory',{}).get('_sName') if isinstance(record.get('_aCategory'),dict) else None
                if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
                self.cache[key]=(self.clock(),deepcopy(item));return item
            finally:
                if owned:client.close()
