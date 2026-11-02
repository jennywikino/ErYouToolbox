"""Read-only image audit and bounded, exact-ID preview repair. No paging."""
import argparse
import json
import math
from pathlib import Path
import sys
import sqlite3
import time
from urllib.parse import urlsplit

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from auto_sync import atomic_json
from backfill_content_ratings import instance_lock
from backfill_previews import (GAMES,fetch_exact_item,open_existing_database,run_backfill,
                               _stored_images,_has_original_metadata)
from eryoutoolbox.models import valid_image_url
from eryoutoolbox.gamebanana import HEADERS,TIMEOUT,_retry_after_seconds
from eryoutoolbox.subscriptions import verified_backup


def official(url):
    if not valid_image_url(url):return False
    p=urlsplit(url)
    return p.scheme=='https' and p.hostname=='images.gamebanana.com' and p.port in (None,443) and p.path.startswith('/img/ss/mods/') and not p.query and not p.fragment


def image_class(raw):
    images=_stored_images(raw)
    if not images:return 'missing'
    parsed=json.loads(raw)
    if len(parsed)==len(images) and all(isinstance(i,dict) and official(i.get('image_url')) and _has_original_metadata(json.dumps([i])) for i in parsed):
        return 'original_metadata'
    return 'thumbnail_or_unverified'


def audit(database,games=GAMES):
    c=open_existing_database(database)
    try:
        result={'total':c.execute('SELECT COUNT(*) FROM mods').fetchone()[0],'games':[]}
        for game in games:
            groups={k:[] for k in ('missing','thumbnail_or_unverified','original_metadata','pending_network_validation','source_no_images')}
            for r in c.execute("SELECT item_id,preview_urls_json FROM mods WHERE source='gamebanana' AND item_type='Mod' AND game_id=? ORDER BY item_id",(game['game_id'],)):
                kind=image_class(r['preview_urls_json']);groups[kind].append(r['item_id'])
                if kind!='missing':groups['pending_network_validation'].append(r['item_id'])
            result['games'].append({**game,'counts':{k:len(v) for k,v in groups.items()},'ids':groups})
        result['missing_total']=sum(g['counts']['missing'] for g in result['games'])
        result['needs_original_total']=sum(g['counts']['thumbnail_or_unverified'] for g in result['games'])
        result['note']='URL availability and source absence cannot be inferred from SQLite alone.'
        return result
    finally:c.close()


class VerifiedClient:
    """Validate the exact response before reusing the existing image extractor."""
    def __init__(self,client,item_id,game):self.client,self.item_id,self.game=client,item_id,game;self.no_images=False;self.status=None;self.wait=None
    def get(self,url):
        response=self.client.get(url);self.status=response.status_code
        self.wait=_retry_after_seconds(response.headers.get('Retry-After'))
        if self.status!=200:return response
        data=response.json()
        if not isinstance(data,dict) or type(data.get('_idRow')) is not int or data['_idRow']!=self.item_id or data.get('_sModelName','Mod')!='Mod' or not isinstance(data.get('_aGame'),dict) or type(data['_aGame'].get('_idRow')) is not int or data['_aGame']['_idRow']!=self.game['game_id']:
            raise ValueError('Source MOD identity/game mismatch')
        media=data.get('_aPreviewMedia')
        if not isinstance(media,dict) or not isinstance(media.get('_aImages'),list):raise ValueError('Image evidence missing; not confirmed image-free')
        self.no_images=media['_aImages']==[]
        return response


def repair(root,database,game,*,limit=10,apply=False,client=None,retry_failed=False):
    if type(limit) is not int or not 1<=limit<=20:raise ValueError('limit must be 1..20')
    root=Path(root);folder=root/'logs/preview_repairs';path=folder/'state.json'
    binding=Path(database).resolve().relative_to(root.resolve()).as_posix()
    with instance_lock(root/'logs/content_ratings/instance.lock'):
        state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'format':'preview-repairs-v1','database':binding,'items':{}}
        if state.get('format')!='preview-repairs-v1' or state.get('database')!=binding:raise ValueError('Checkpoint mismatch; original retained')
        now=time.time();cool=folder/'cooldown.json'
        if cool.exists() and now<json.loads(cool.read_text())['not_before']:return {'status':'cooldown','requests':0}
        c=open_existing_database(database)
        try:
            rows=[dict(r) for r in c.execute("SELECT item_id,preview_urls_json FROM mods WHERE source='gamebanana' AND item_type='Mod' AND game_id=? ORDER BY item_id",(game['game_id'],))]
            candidates=[r for r in rows if image_class(r['preview_urls_json'])!='original_metadata' and now>=state['items'].get(str(r['item_id']),{}).get('next_check',0)]
            candidates.sort(key=lambda r:(0 if retry_failed and state['items'].get(str(r['item_id']),{}).get('status')=='failed' else 1,r['item_id']))
        finally:c.close()
        report={'game':game,'dry_run':not apply,'requests':0,'processed':[],'obtained_images':[],'source_no_images':[],'failed':[],'to_update':[],'updated':0,'checked_at':now,'backup':None}
        records=[];observed={}
        own=client is None
        if own:client=httpx.Client(timeout=TIMEOUT,headers=HEADERS)
        try:
            for row in candidates[:limit]:
                item_id=row['item_id'];report['processed'].append(item_id)
                if report['requests']:time.sleep(2)
                verified=VerifiedClient(client,item_id,game);report['requests']+=1
                try:
                    fetched=fetch_exact_item(verified,item_id,game)
                    if fetched['failure_reasons']:raise ValueError(str(fetched['failure_reasons']))
                    record=fetched['records'][0]
                    images=record['preview_images']
                    if verified.no_images:
                        report['source_no_images'].append(item_id);observed[str(item_id)]={'status':'source_no_images','checked_at':now,'next_check':now+7*86400};continue
                    if not images or any(not all(official(i[k]) for k in ('image_url','thumbnail_url','switch_url')) for i in images):raise ValueError('No trustworthy original URL from official _sFile fields')
                    records.append(record);report['obtained_images'].append(item_id)
                    observed[str(item_id)]={'status':'verified','checked_at':now,'next_check':now+7*86400}
                except (ValueError,TypeError,KeyError,httpx.HTTPError) as exc:
                    report['failed'].append({'item_id':item_id,'http_status':verified.status,'reason':str(exc)[:500]})
                    observed[str(item_id)]={'status':'failed','checked_at':now,'next_check':now+3600}
                    if verified.status in (429,403):
                        wait=verified.wait
                        atomic_json(cool,{'not_before':time.time()+max(wait if isinstance(wait,(int,float)) and math.isfinite(wait) else 86400,1)})
                        break
        finally:
            if own:client.close()
        c=open_existing_database(database,read_only=not apply)
        try:
            def backup():report['backup']=str(verified_backup(database))
            plan=run_backfill(c,records,limit=limit,dry_run=not apply,before_write=backup,game=game)
            report['to_update']=[u['identity'][2] for u in plan['updates']];report['updated']=plan['updated']
        except BaseException as exc:
            if apply:c.rollback()
            report.update(status='failed',error=str(exc)[:500])
            atomic_json(folder/('apply_latest.json' if apply else 'preview_latest.json'),report)
            raise
        finally:c.close()
        if apply:
            state['items'].update(observed);atomic_json(path,state)
        report['status']='partial' if report['failed'] else 'success'
        atomic_json(folder/('apply_latest.json' if apply else 'preview_latest.json'),report)
        return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--audit',action='store_true');p.add_argument('--game',type=int);p.add_argument('--limit',type=int,default=10);p.add_argument('--retry-failed',action='store_true')
    mode=p.add_mutually_exclusive_group();mode.add_argument('--dry-run',action='store_true');mode.add_argument('--apply',action='store_true');args=p.parse_args()
    db=ROOT/'data/eryoutoolbox.db'
    try:
        if args.audit:
            report=audit(db);atomic_json(ROOT/'logs/preview_repairs/audit.json',report)
            print(json.dumps({**report,'games':[{k:v for k,v in g.items() if k!='ids'} for g in report['games']]},ensure_ascii=False,indent=2))
        else:
            game=next((g for g in GAMES if g['game_id']==args.game),None)
            if game is None:raise ValueError('Choose a configured --game; batches are game-specific')
            print(json.dumps(repair(ROOT,db,game,limit=args.limit,apply=args.apply,retry_failed=args.retry_failed),ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:print(f'Preview repair failed: {exc}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
