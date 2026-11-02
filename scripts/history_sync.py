"""Bounded historical publication scan. Reuses collector/importer; opt-in only."""
import argparse
from contextlib import nullcontext
import json
import math
from pathlib import Path
import secrets
import sys
import threading
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from auto_sync import AutoSync, atomic_json
from backfill_content_ratings import instance_lock
from web_sync import WebSync, utc, fingerprint
from eryoutoolbox.gamebanana import collect_game, HEADERS, TIMEOUT
from eryoutoolbox.database import connect_database
from eryoutoolbox.importer import import_samples, parse_utc, DB_FIELDS
from eryoutoolbox.content_ratings import source_ratings
from eryoutoolbox.subscriptions import verified_backup
from eryoutoolbox.ui_queries import readonly_connection

FORMAT = 'eryoutoolbox-history-v1'
SORT = 'Generic_Newest'
DEFAULTS = {'enabled':False, 'paused':False, 'max_pages':2}
INTERVAL = 86400


class HistorySync:
    def __init__(self, root, database=None, games=None, mode_provider=None):
        self.root = Path(root).resolve()
        self.database = Path(database) if database else self.root/'data/eryoutoolbox.db'
        self.binding = self.database.resolve().relative_to(self.root).as_posix()
        self.games = games if games is not None else json.loads((self.root/'config/games.json').read_text(encoding='utf-8'))['games']
        if not 1 <= len(self.games) <= 6: raise ValueError('Expected 1..6 configured games')
        self.directory = self.root/'logs/history_sync'
        self.mode_provider = mode_provider or AutoSync(self.root, self.database, self.games).settings
        self.running = threading.Lock()

    def settings(self):
        path = self.directory/'settings.json'
        value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(DEFAULTS)
        if (not isinstance(value,dict) or set(value)!=set(DEFAULTS) or
            type(value['enabled']) is not bool or type(value['paused']) is not bool or
            type(value['max_pages']) is not int or not 1<=value['max_pages']<=5):
            raise ValueError('Invalid history settings; original file retained')
        return value

    def configure(self, value):
        if not isinstance(value,dict) or set(value)!=set(DEFAULTS): raise ValueError('Invalid history settings')
        if type(value['enabled']) is not bool or type(value['paused']) is not bool or type(value['max_pages']) is not int or not 1<=value['max_pages']<=5:
            raise ValueError('History max_pages must be 1..5; enabled/paused must be boolean')
        with instance_lock(self.directory/'settings.lock'):
            atomic_json(self.directory/'settings.json', value)
        return self.status()

    def state(self):
        path = self.directory/'state.json'
        value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'format':FORMAT,'database':self.binding,'games':{}}
        if value.get('format')!=FORMAT or value.get('database')!=self.binding or not isinstance(value.get('games'),dict):
            raise ValueError('History journal identity mismatch; original retained')
        value['not_before']=max(value.get('not_before',0),self.cooldown_until())
        return value

    def cooldown_until(self):
        path=self.directory/'cooldown.json'
        value=json.loads(path.read_text(encoding='utf-8'))['not_before'] if path.exists() else 0
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise ValueError('Invalid source cooldown; original retained')
        return value

    def committed(self):
        c = readonly_connection(self.database)
        found = {}
        try:
            for row in c.execute("SELECT game_id,error_summary FROM sync_runs WHERE source='gamebanana' AND json_valid(error_summary) AND json_type(error_summary,'$.history_scan')='object' ORDER BY run_id DESC"):
                item = json.loads(row['error_summary'])['history_scan']
                if item.get('format')!=FORMAT or item.get('database')!=self.binding: continue
                cp = item['checkpoint']
                if cp.get('sort')!=SORT or cp.get('game_id')!=row['game_id'] or type(cp.get('page')) is not int or cp['page']<1 or type(cp.get('per_page')) is not int or not 1<=cp['per_page']<=50 or not isinstance(cp.get('boundary_ids'),list) or len(cp['boundary_ids'])>cp['per_page'] or any(type(i) is not int or i<=0 for i in cp['boundary_ids']) or len(set(cp['boundary_ids']))!=len(cp['boundary_ids']):
                    raise ValueError('Invalid committed historical checkpoint; refusing to skip pages')
                found.setdefault(str(row['game_id']), cp)
        finally: c.close()
        return found

    def status(self):
        settings, state = self.settings(), self.state()
        path = self.directory/'latest.json'
        report = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if report and report.get('status')=='checking':
            try:
                with instance_lock(self.root/'logs/content_ratings/instance.lock'):
                    report = {**report,'status':'stopped','error':'Interrupted worker; committed boundary will be rechecked'}
            except RuntimeError: pass
        checkpoints = self.committed()
        games = [{**g, **state['games'].get(str(g['game_id']),{}), 'checkpoint':checkpoints.get(str(g['game_id']))} for g in self.games]
        return {'settings':settings, 'interval_hours':24, 'games':games, 'last_run':report,
                'not_before':state.get('not_before',0), 'coverage':'incomplete'}

    def launch(self):
        if not self.running.acquire(blocking=False): return {'status':'already_running'}
        def work():
            try: self.run()
            except Exception as exc:
                # A competing job must never have its report replaced.
                if not isinstance(exc,RuntimeError) or 'instance is active' not in str(exc):
                    atomic_json(self.directory/'latest.json',{'status':'failed','error':str(exc),'ended_at':utc(),'requests':0})
            finally: self.running.release()
        threading.Thread(target=work,daemon=False).start()
        return {'status':'requested'}

    def _protect(self, connection, records):
        """Preserve richer local fields; an older source version only fills holes."""
        protected = []
        for incoming in records:
            r = dict(incoming)
            old = connection.execute('SELECT * FROM mods WHERE source=? AND item_type=? AND item_id=?', (r['source'],r['item_type'],r['item_id'])).fetchone()
            if old:
                if old['game_id'] is not None and old['game_id']!=r['game_id']: raise ValueError('Local/source game identity conflict')
                stale = any(parse_utc(old[f]) and (not parse_utc(r.get(f)) or parse_utc(old[f])>parse_utc(r[f])) for f in ('updated_at','modified_at'))
                # A newly captured HTTP response alone does not establish that
                # an undated source version is newer than local metadata.
                stale = stale or not any(parse_utc(old[f]) and parse_utc(r.get(f)) for f in ('updated_at','modified_at'))
                if stale:
                    for field in DB_FIELDS:
                        value = old[field]
                        if field=='raw_metadata_json' or value in (None,'','[]','{}'): continue
                        target = {'tags_json':'tags','preview_urls_json':'preview_images'}.get(field,field)
                        r[target] = json.loads(value) if field.endswith('_json') else value
                if old['preview_urls_json'] and json.loads(old['preview_urls_json']): r['preview_images']=json.loads(old['preview_urls_json'])
                if old['content_rating_status'] not in (None,'','UNKNOWN'): r['content_rating_status']=old['content_rating_status']
                rating = source_ratings(old['raw_metadata_json'])
                if rating['verification']!='unverified_labels': r['source_rating_fields']=rating['raw']
            protected.append(r)
        return protected

    def run(self, *, dry_run=False, game=None, max_pages=None, client=None, lock_held=False):
        if not self.database.is_file(): raise ValueError('Existing database required; no initialization is performed')
        with nullcontext() if lock_held else instance_lock(self.root/'logs/content_ratings/instance.lock'):
            return self._run(dry_run,game,max_pages,client)

    def _run(self, dry_run, game, max_pages, client):
        settings, state = self.settings(), self.state()
        mode = 'check' if dry_run else self.mode_provider()['mode']
        if not dry_run and (mode=='off' or not settings['enabled'] or settings['paused']): return {'status':'disabled','requests':0}
        now = time.time()
        if now<state.get('not_before',0): return {'status':'cooldown','not_before':state['not_before'],'requests':0}
        daily = WebSync(self.database,self.root,self.games)
        if daily.state.get('status')=='waiting' and not daily.state.get('automatic') and daily.candidate and now-daily.candidate['created']<=600:
            return {'status':'manual_preview_pending','requests':0}
        budget = settings['max_pages'] if max_pages is None else max_pages
        if type(budget) is not int or not 1<=budget<=5: raise ValueError('max_pages must be 1..5')
        selected = [g for g in self.games if game is None or g['game_id']==game]
        if not selected: raise ValueError('Unknown configured game')
        committed = self.committed()
        report = {'format':FORMAT,'status':'checking','dry_run':dry_run,'mode':mode,'started_at':utc(),
                  'requests':0,'request_budget':len(selected)*budget,'games':[], 'coverage':'incomplete'}
        destination = self.directory/('preview_latest.json' if dry_run else 'latest.json')
        # Supplied clients are used by bounded real probes and offline tests.
        with nullcontext(client) if client is not None else httpx.Client(timeout=TIMEOUT,headers=HEADERS) as source:
            for g in selected:
                gid = str(g['game_id']); attempt = state['games'].get(gid,{})
                if not dry_run and now<attempt.get('last_attempt_epoch',-INTERVAL)+INTERVAL:
                    report['games'].append({'game_id':g['game_id'],'name':g['name'],'status':'not_due'}); continue
                if not dry_run:
                    current=self.settings()
                    if current['paused'] or not current['enabled'] or self.mode_provider()['mode']=='off':
                        report['stopped']=True;break
                entry = self._scan(source,g,committed.get(gid),attempt,budget,mode,dry_run,state,report,destination)
                report['games'].append(entry)
                report['requests'] += entry['requests']
                atomic_json(destination,report)
                if entry.get('stop_all') or entry['status']=='stopped': break
        attempted={g['game_id'] for g in report['games']}
        for g in selected:
            if g['game_id'] not in attempted:
                report['games'].append({'game_id':g['game_id'],'name':g['name'],'status':'skipped','requests':0,
                                        'reason':'Stopped before this game; existing checkpoint retained'})
        acted = [g for g in report['games'] if g['status']!='not_due']
        report['status'] = ('stopped' if report.get('stopped') or any(g['status']=='stopped' for g in acted) else
                            'not_due' if not acted else 'success' if all(g['status']=='success' for g in acted) else
                            'partial' if any(g['status'] in ('success','partial') or g.get('committed') for g in acted) else 'failed')
        report['ended_at'] = utc()
        if state.get('not_before'): report['not_before']=state['not_before']
        atomic_json(destination,report)
        atomic_json(self.directory/(('preview_' if dry_run else 'run_')+secrets.token_hex(10)+'.json'),report)
        return report

    def _scan(self, client, game, checkpoint, attempt, budget, mode, dry_run, state, report, destination):
        started = utc(); gid=str(game['game_id'])
        entry = {'game_id':game['game_id'],'name':game['name'],'status':'checking','requests':0,'fetched':0,
                 'duplicates':0,'pages':[],'failures':[],'coverage':'incomplete','source_end_observed':False}
        previous = checkpoint or {}
        per_page = previous.get('per_page',50)
        frontier = previous.get('page',0)
        recovery = attempt.get('drift')
        start = max(1,frontier-1) if recovery and recovery.get('direction')=='earlier' else max(1,frontier)
        planned = list(range(start,start+budget))
        records=[]; seen=set(); prior_time=None; actual_size=None; prior_total=None; anchor_found=not frontier
        if not dry_run:
            state['games'][gid]={**attempt,'last_attempt_epoch':time.time(),'last_scan_at':started,'status':'checking'}
            atomic_json(self.directory/'state.json',state)
            atomic_json(destination,{**report,'current_game':game['name'],'status':'checking'})
        last_page=None; detected_drift=None
        try:
            for page in planned:
                if entry['requests']>=budget: break
                if not dry_run:
                    current=self.settings()
                    if current['paused'] or not current['enabled'] or self.mode_provider()['mode']=='off': raise InterruptedError('Paused or disabled; boundary not advanced')
                if entry['requests']: time.sleep(1)
                result = collect_game(client,game,max_pages=1,per_page=per_page,start_page=page,sort=SORT,
                                      max_requests=budget-entry['requests'],max_rate_wait=0)
                entry['requests']+=result['request_count']
                entry['fetched']+=sum(p.get('returned_count',0) for p in result.get('pagination_pages',[])) or result['actual_record_count']
                if result['failure_reasons']:
                    for failure in result['failure_reasons']:
                        if failure.get('http_status') in (429,403):
                            entry['stop_all']=True
                            wait=failure.get('retry_after_seconds')
                            state['not_before']=time.time()+max(wait if isinstance(wait,(int,float)) and math.isfinite(wait) else INTERVAL,1)
                            # Cooldown is operational safety, not committed scan
                            # progress. Keep it even for a failed explicit dry-run.
                            atomic_json(self.directory/'cooldown.json',{'not_before':state['not_before'],'http_status':failure['http_status'],'observed_at':utc()})
                    entry['failures'].extend(result['failure_reasons'])
                    raise ValueError('Source request failed; current page is uncommitted')
                pagination = result['pagination_pages'][0] if len(result['pagination_pages'])==1 else {}
                size, total = pagination.get('metadata_per_page'), pagination.get('record_count')
                rows = result['records']; ids=[r.get('item_id') for r in rows]
                if type(size) is not int or total is None or pagination.get('error') or pagination.get('returned_count')!=len(rows):
                    raise ValueError('Missing/inconsistent pagination metadata or duplicate rows')
                if actual_size is not None and size!=actual_size or frontier and size!=per_page:
                    raise ValueError('Server pagination size changed; checkpoint cannot be reused')
                if prior_total is not None and total!=prior_total:
                    raise ValueError('Source record count changed while paging; current boundary must be retried')
                prior_total=total
                actual_size=size;per_page=size
                times=[parse_utc(r.get('created_at')) for r in rows]
                if any(t is None for t in times): raise ValueError('Missing/invalid source publication time')
                if any(a<b for a,b in zip(times,times[1:])) or prior_time and times and prior_time<times[0]:
                    raise ValueError('Observed publication order is not descending')
                if times: prior_time=times[-1]
                for row in rows:
                    if row.get('source')!='gamebanana' or row.get('item_type')!='Mod' or type(row.get('item_id')) is not int or row['item_id']<1 or row.get('game_id')!=game['game_id']:
                        raise ValueError('MOD source/type/ID/game identity mismatch')
                if frontier and page==frontier and not recovery:
                    if ids!=previous['boundary_ids']:
                        common=[(ids.index(i)-previous['boundary_ids'].index(i)) for i in ids if i in previous['boundary_ids']]
                        detected_drift={'page':page,'observed_ids':ids,'direction':'earlier' if common and min(common)<0 else 'later','observed_at':utc()}
                        raise ValueError('Pagination drift detected; pause advancement and revalidate overlapping boundary next run')
                    anchor_found=True
                if recovery:
                    # Bounded relocation of multiple tail IDs, not a blind page-number resume.
                    tail=previous.get('boundary_ids',[])[-3:]
                    for i in ids:
                        if i in tail: seen.add(('anchor',i))
                    anchor_found=sum(('anchor',i) in seen for i in tail)>=min(2,len(tail))
                    if page==recovery['page'] and ids!=recovery['observed_ids']:
                        entry['boundary_changed_again']=True
                for row in rows:
                    key=(row['source'],row['item_type'],row['item_id'])
                    if key in seen: entry['duplicates']+=1
                    else: seen.add(key); records.append(row)
                entry['pages'].append({'page':page,'count':len(rows),'per_page':size,'total':total,
                                       'oldest':rows[-1]['created_at'] if rows else None,'newest':rows[0]['created_at'] if rows else None,
                                       'boundary_ids':ids,'sort_observed_descending':True})
                last_page=entry['pages'][-1]
                entry['source_end_observed']=page*size>=total
                if entry['source_end_observed']: break
            if recovery and not anchor_found: raise ValueError('Cannot relocate saved boundary anchors within bounded overlap; paused, no progress committed')
            if recovery:entry['boundary_relocated']=True
            if not last_page: raise ValueError('No validated page within request budget')
        except (KeyboardInterrupt,InterruptedError) as exc:
            entry['status']='stopped';entry['failures'].append({'reason':str(exc) or 'KeyboardInterrupt'})
        except (ValueError,TypeError,KeyError,httpx.HTTPError) as exc:
            entry['status']='failed'
            if not entry['failures']:entry['failures'].append({'page':page,'reason':str(exc)})
        # A drift/order/identity failure never imports an uncertain prefix.
        invalid = detected_drift is not None or (entry['failures'] and not any(f.get('http_status') or 'Timeout' in f.get('reason','') for f in entry['failures']))
        if invalid or not anchor_found or entry['status']=='stopped': records=[];last_page=None
        if detected_drift:entry['drift']=detected_drift
        cp = {'game_id':game['game_id'],'sort':SORT,'per_page':actual_size or per_page,'page':last_page['page'] if last_page else frontier,
              'boundary_ids':last_page['boundary_ids'] if last_page else previous.get('boundary_ids',[]),
              'last_committed_at':utc(),'last_scan_at':started,'coverage':'incomplete',
              'source_end_observed':entry['source_end_observed'],'oldest':last_page['oldest'] if last_page else previous.get('oldest')}
        if last_page:
            connection=readonly_connection(self.database) if mode=='check' else connect_database(self.database)
            backup=None
            def before():
                nonlocal backup
                backup=verified_backup(self.database)
            def guard(c):
                current=self.settings()
                if self.mode_provider()['mode']!='apply' or not current['enabled'] or current['paused']: raise ValueError('History apply authorization changed')
                # Recheck formal checkpoint under the importer write transaction.
                if self.committed().get(gid)!=checkpoint: raise ValueError('Historical progress changed; retry overlap')
                if fingerprint(c)!=baseline: raise ValueError('MOD metadata changed after history preview; retry overlap')
            try:
                baseline=fingerprint(connection)
                safe=self._protect(connection,records)
                snapshots=[({'captured_at':parse_utc(started)},safe)]
                preview=import_samples(connection,snapshots,dry_run=True)
                entry.update(newly_collected_old=preview['inserted'],existing=preview['unique_records']-preview['inserted'],
                             source_updates=preview['source_update_events'],metadata_only=preview['updated']-preview['source_update_events'],
                             unchanged=preview['unchanged'],unique=preview['unique_records'])
                if mode=='apply':
                    applied=import_samples(connection,snapshots,dry_run=False,precondition=guard,before_write=before,
                        sync_run={'source':'gamebanana','game_id':game['game_id'],'started_at':started,'ended_at':utc(),
                                  'status':'partial' if entry['failures'] else 'success','request_count':entry['requests'],
                                  'fetched_count':entry['fetched'],'deduplicated_count':preview['unique_records'],'errors':entry['failures'],
                                  'history_scan':{'format':FORMAT,'database':self.binding,'checkpoint':cp}})
                    entry['committed']=True;entry['inserted']=applied['inserted'];entry['backup']=str(backup)
                    entry['checkpoint']=cp
                else: entry['proposed_checkpoint']=cp
                entry['status']='partial' if entry['failures'] else 'success'
            except BaseException as exc:
                entry['status']='stopped' if isinstance(exc,KeyboardInterrupt) else 'failed'
                entry['failures'].append({'reason':f'Import rolled back / not committed: {exc}'})
            finally:connection.close()
        if not dry_run:
            updated={**state['games'][gid],'status':entry['status'],'failures':entry['failures'],'scanned_pages':[p['page'] for p in entry['pages']],
                     'current_position':last_page['page'] if last_page else frontier}
            if detected_drift: updated['drift']=detected_drift
            elif entry.get('committed'): updated.pop('drift',None)
            if entry.get('checkpoint'): updated['checkpoint']=entry['checkpoint']
            state['games'][gid]=updated
            atomic_json(self.directory/'state.json',state)
        return entry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game',type=int,required=True)
    parser.add_argument('--max-pages',type=int,default=2)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--dry-run',action='store_true');mode.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    try:
        result=HistorySync(ROOT).run(dry_run=not args.apply,game=args.game,max_pages=args.max_pages)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 1 if result['status']=='failed' else 0
    except (ValueError,OSError,RuntimeError) as exc:
        print(f'History scan stopped: {exc}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
