"""Local author browsing and bounded Member URL metadata cache (no image download)."""
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
import httpx
from .gamebanana import HEADERS,TIMEOUT,_retry_after_seconds
from .ui_queries import readonly_connection

FIELDS='name,Url().sAvatarUrl(),Url().sHdAvatarUrl(),Url().sProfileUrl()'
_lock=threading.Lock()
_fill_lock=threading.Lock()
_next_fill=0.0
_blocked_until=0.0


def fill_one(root, authors, *, client=None):
    """At most one serial Member request per call and two seconds globally.

    No background fan-out. Existing seven-day cache is still authoritative.
    """
    global _next_fill
    if not _fill_lock.acquire(blocking=False):return
    try:
        if time.time()<_next_fill:return
        for author in authors:
            if author['source']!='gamebanana':continue
            cached=member(root,author['source'],author['author_id'])
            if cached.get('expires',0)>time.time():continue
            _next_fill=time.time()+2
            profile=member(root,author['source'],author['author_id'],client=client,fetch=True)
            author['avatar_url']=profile.get('avatar_url')
            return
    finally:_fill_lock.release()

def avatar_url(value):
    if not isinstance(value,str):return None
    try:
        u=urlsplit(value)
        if u.scheme=='https' and u.hostname=='images.gamebanana.com' and not u.username and not u.password and u.port in (None,443) and not u.query and not u.fragment and u.path.startswith('/img/av/') and '..' not in u.path and '%' not in u.path and '\\' not in value:
            return value
    except ValueError:pass
    return None

def member(root,source,aid,client=None,fetch=False):
    global _blocked_until
    if not source or type(aid) is not int or aid<=0:raise ValueError('Invalid author')
    if source!='gamebanana':return {'avatar_url':None}
    path=Path(root)/'logs/author_profiles'/f'{aid}.json'
    with _lock:
        try:cached=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        except (OSError,ValueError):cached=None
        if not isinstance(cached,dict):cached=None
        if cached and cached.get('author_id')==aid and time.time()<cached.get('expires',0):
            return {**cached,'avatar_url':avatar_url(cached.get('avatar_url'))}
        if not fetch:return {'avatar_url':None}
        if time.time()<_blocked_until:return {'avatar_url':None,'error':'Member API cooldown','expires':_blocked_until}
        result={'author_id':aid,'avatar_url':None,'expires':time.time()+3600}
        own=client is None
        if own:client=httpx.Client(timeout=TIMEOUT,headers=HEADERS)
        try:
            response=client.get('https://api.gamebanana.com/Core/Item/Data',params={'itemtype':'Member','itemid':aid,'fields':FIELDS,'return_keys':1})
            if response.status_code in (403,429):
                result['error']=f'HTTP {response.status_code}; stopped';result['expires']=time.time()+max(7*86400,_retry_after_seconds(response.headers.get('Retry-After')) or 0)
                _blocked_until=time.time()+max(_retry_after_seconds(response.headers.get('Retry-After')) or 3600,1)
            else:
                response.raise_for_status();data=response.json()
                if not isinstance(data,dict) or data.get('Url().sProfileUrl()')!=f'https://gamebanana.com/members/{aid}':raise ValueError('Member identity mismatch')
                result.update(name=data.get('name'),profile_url=data['Url().sProfileUrl()'],avatar_url=avatar_url(data.get('Url().sAvatarUrl()')) or avatar_url(data.get('Url().sHdAvatarUrl()')),expires=time.time()+7*86400)
        except (httpx.HTTPError,ValueError) as exc:result['error']=str(exc)
        finally:
            if own:client.close()
        path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');temp.replace(path)
        return result

def author_list(database,*,search='',limit=20,offset=0,source=None,author_id=None):
    if not 1<=limit<=20 or offset<0:raise ValueError('Invalid pagination')
    c=readonly_connection(database)
    try:
        # Include a specific local author even when not followed; never match by nickname.
        base="SELECT source,author_id,display_name FROM author_subscriptions"
        args=[]
        if author_id is not None:
            if type(author_id) is not int or author_id<=0 or not source:raise ValueError('Invalid author')
            base="SELECT source,author_id,MAX(author_name) AS display_name FROM mods WHERE source=? AND author_id=? GROUP BY source,author_id";args=[source,author_id]
        sql="SELECT a.source,a.author_id,COALESCE(NULLIF(a.display_name,''),(SELECT m.author_name FROM mods m WHERE m.source=a.source AND m.author_id=a.author_id ORDER BY julianday(m.created_at) DESC,m.item_id DESC LIMIT 1),'暂无作者') AS name,(SELECT COUNT(*) FROM mods m WHERE m.source=a.source AND m.author_id=a.author_id) AS mod_count,(SELECT MAX(julianday(m.created_at)) FROM mods m WHERE m.source=a.source AND m.author_id=a.author_id) AS latest_sort,(SELECT m.created_at FROM mods m WHERE m.source=a.source AND m.author_id=a.author_id AND julianday(m.created_at) IS NOT NULL ORDER BY julianday(m.created_at) DESC,m.item_id DESC LIMIT 1) AS latest_created_at FROM ("+base+") a"
        clause=' WHERE name LIKE ?' if search else ''
        if search:args.append('%'+search+'%')
        total=c.execute('SELECT COUNT(*) FROM ('+sql+')'+clause,args).fetchone()[0]
        rows=c.execute('SELECT * FROM ('+sql+')'+clause+' ORDER BY latest_sort DESC,source,author_id LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
        followed=c.execute('SELECT COUNT(*) FROM author_subscriptions').fetchone()[0]
        return {'items':[dict(r) for r in rows],'total_count':total,'followed_count':followed}
    finally:c.close()
