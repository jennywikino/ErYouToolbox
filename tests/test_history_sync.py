"""Offline historical scan tests: real temporary SQLite, mock HTTP transport."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from history_sync import HistorySync, DEFAULTS, FORMAT
from auto_sync import AutoSync, DEFAULTS as AUTO_DEFAULTS
from backfill_content_ratings import instance_lock
from web_sync import WebSync
from eryoutoolbox.database import initialize_database,connect_database


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.db=self.root/'data/eryoutoolbox.db';initialize_database(self.db)
        self.games=[{'game_id':8552+i,'name':f'Game {i}'} for i in range(6)]
        self.mode={'mode':'apply'};self.now=2_000_000_000
        self.clock=patch('history_sync.time.time',side_effect=lambda:self.now);self.clock.start()
        self.sleep=patch('eryoutoolbox.gamebanana.time.sleep');self.sleep_mock=self.sleep.start()
        self.h=HistorySync(self.root,self.db,self.games,mode_provider=lambda:self.mode)
        self.h.configure({**DEFAULTS,'enabled':True})
        self.rows={g['game_id']:list(range(8+i*100, i*100,-1)) for i,g in enumerate(self.games)}
        self.requests=[];self.overrides={};self.row_changes={}

    def tearDown(self):self.sleep.stop();self.clock.stop();self.tmp.cleanup()

    def record(self,i,gid):
        return {'_idRow':i,'_sModelName':'Mod','_sName':f'Mod {i}',
                '_aGame':{'_idRow':gid},'_aSubmitter':{'_idRow':7,'_sName':'Author'},
                '_tsDateAdded':1_600_000_000+i*100,'_tsDateModified':1_600_000_000+i*100,
                **self.row_changes.get(i,{})}

    def client(self):
        def respond(request):
            p=request.url.params;gid=int(p['_aFilters[Generic_Game]']);page=int(p['_nPage'])
            self.assertEqual(p['_sSort'],'Generic_Newest')
            self.requests.append((gid,page))
            override=self.overrides.get((gid,page))
            if isinstance(override,BaseException):raise override
            if override is not None:return override(request) if callable(override) else httpx.Response(200,json=override)
            rows=self.rows[gid][(page-1)*2:page*2]
            return httpx.Response(200,json={'_aRecords':[self.record(i,gid) for i in rows],
                                           '_aMetadata':{'_nPerpage':2,'_nRecordCount':len(self.rows[gid])}})
        return httpx.Client(transport=httpx.MockTransport(respond))

    def run_scan(self,all_games=False,**kwargs):
        with self.client() as client:return self.h.run(client=client,game=None if all_games else 8552,**kwargs)

    def next_day(self):self.now+=86401;self.requests.clear()
    def count(self,table):
        c=connect_database(self.db)
        try:return c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
        finally:c.close()

    def test_first_and_second_scan_actual_page_size_and_no_duplicates(self):
        first=self.run_scan();self.assertEqual(first['status'],'success');self.assertEqual(first['requests'],2)
        self.assertEqual(self.count('mods'),4);self.assertEqual(self.h.committed()['8552']['page'],2)
        self.assertEqual(self.h.committed()['8552']['per_page'],2)
        self.next_day();second=self.run_scan()
        self.assertEqual([p for _,p in self.requests],[2,3]);self.assertEqual(self.count('mods'),6)
        self.assertEqual(self.h.committed()['8552']['page'],3);self.assertEqual(second['coverage'],'incomplete')
        self.assertEqual(len(list((self.db.parent/'backups').glob('*.db'))),2)

    def test_six_independent_and_daily_checkpoints_untouched(self):
        result=self.run_scan(all_games=True)
        self.assertEqual(result['requests'],12);self.assertEqual(len(self.h.committed()),6)
        self.assertEqual(self.count('mods'),24)
        self.assertEqual(WebSync(self.db,self.root,self.games).committed(),{})
        self.assertFalse((self.root/'logs/web_sync/task.json').exists())

    def test_repeated_ids_deduplicate(self):
        self.rows[8552]=[8,7,7,6,5,4]
        report=self.run_scan();self.assertEqual(self.count('mods'),3)
        self.assertEqual(report['games'][0]['duplicates'],1)

    def test_daily_limit_and_disabled_and_pause(self):
        self.run_scan();before=self.count('mods');self.requests.clear()
        self.assertEqual(self.run_scan()['status'],'not_due');self.assertFalse(self.requests)
        self.mode['mode']='off';self.assertEqual(self.run_scan()['status'],'disabled')
        self.mode['mode']='apply';self.h.configure({**DEFAULTS,'enabled':True,'paused':True})
        self.assertEqual(self.run_scan()['status'],'disabled');self.assertEqual(before,self.count('mods'))

    def test_insert_drift_pauses_then_revalidates(self):
        self.run_scan();old=self.h.committed();self.rows[8552].insert(0,9);self.next_day()
        report=self.run_scan();self.assertEqual(report['status'],'failed');self.assertEqual(self.h.committed(),old)
        self.assertEqual(self.h.state()['games']['8552']['drift']['direction'],'later')
        self.next_day();report=self.run_scan();self.assertEqual(report['status'],'success')
        self.assertEqual(self.h.committed()['8552']['page'],3)
        self.assertEqual(self.count('mods'),5) # Four original rows plus newly reached 4.

    def test_delete_drift_rechecks_earlier_overlap(self):
        self.run_scan();old=self.h.committed();self.rows[8552].remove(8);self.next_day()
        self.run_scan();self.assertEqual(self.h.committed(),old)
        self.next_day();report=self.run_scan();self.assertEqual([p for _,p in self.requests],[1,2])
        self.assertEqual(report['status'],'success');self.assertEqual(self.h.committed()['8552']['page'],2)

    def test_boundary_moves_again_but_tail_anchors_can_be_relocated(self):
        self.run_scan();self.rows[8552].insert(0,9);self.next_day();self.run_scan()
        self.rows[8552].insert(0,10);self.next_day();result=self.run_scan()
        self.assertEqual(result['status'],'success')
        self.assertTrue(result['games'][0]['boundary_relocated'])
        self.assertTrue(result['games'][0]['boundary_changed_again'])
        self.assertEqual(self.h.committed()['8552']['page'],3)

    def test_metadata_count_changes_mid_scan_no_progress(self):
        self.overrides[(8552,2)]={'_aRecords':[self.record(6,8552),self.record(5,8552)],'_aMetadata':{'_nPerpage':2,'_nRecordCount':9}}
        self.assertEqual(self.run_scan()['status'],'failed');self.assertFalse(self.h.committed())

    def test_clock_rollback_does_not_bypass_daily_interval(self):
        self.run_scan();self.now-=100;self.requests.clear()
        self.assertEqual(self.run_scan()['status'],'not_due');self.assertFalse(self.requests)

    def test_large_unrelocatable_drift_does_not_advance(self):
        self.run_scan();old=self.h.committed();self.rows[8552]=list(range(100,80,-1));self.next_day();self.run_scan()
        self.next_day();self.run_scan();self.assertEqual(old,self.h.committed())

    def test_partial_page_or_empty_without_metadata_not_committed(self):
        for payload in [ {'_aRecords':[],'_aMetadata':{}},
                         {'_aRecords':[self.record(8,8552)],'_aMetadata':{'_nPerpage':2,'_nRecordCount':8}} ]:
            self.overrides[(8552,1)]=payload;self.next_day();result=self.run_scan()
            self.assertEqual(result['status'],'failed');self.assertFalse(self.h.committed());self.assertEqual(self.count('mods'),0)

    def test_sort_missing_time_and_identity_anomalies(self):
        for changes in [{'_tsDateAdded':None},{'_aGame':{'_idRow':1}},{'_sModelName':'Member'},{'_tsDateAdded':1}]:
            self.row_changes[8]=changes;self.next_day();self.assertEqual(self.run_scan()['status'],'failed')
            self.assertFalse(self.h.committed());self.assertEqual(self.count('mods'),0)

    def test_source_end_observation_not_absolute_coverage(self):
        self.rows[8552]=[8,7,6];result=self.run_scan()
        self.assertTrue(self.h.committed()['8552']['source_end_observed'])
        self.assertEqual(result['coverage'],'incomplete');self.assertEqual(self.count('mods'),3)

    def test_429_retry_after_no_wait_and_stop_other_games(self):
        self.overrides[(8552,1)]=lambda r:httpx.Response(429,headers={'Retry-After':'100000'})
        result=self.run_scan(all_games=True);self.assertEqual(result['requests'],1)
        self.assertEqual(len(self.requests),1);self.assertFalse(self.h.committed())
        self.next_day();self.assertEqual(self.run_scan()['status'],'cooldown');self.assertFalse(self.requests)
        self.assertFalse(any(call.args and call.args[0]==100000 for call in self.sleep_mock.mock_calls))

    def test_dry_run_429_retains_cooldown_but_not_checkpoint(self):
        self.overrides[(8552,1)]=lambda r:httpx.Response(429,headers={'Retry-After':'60'})
        self.run_scan(dry_run=True);self.requests.clear()
        self.assertFalse((self.h.directory/'state.json').exists())
        self.assertTrue((self.h.directory/'cooldown.json').exists())
        self.assertEqual(self.run_scan(dry_run=True)['status'],'cooldown');self.assertFalse(self.requests)
        self.assertEqual(self.count('mods'),0)

    def test_403_stops_without_retry(self):
        self.overrides[(8552,1)]=lambda r:httpx.Response(403)
        result=self.run_scan(all_games=True)
        self.assertEqual(len(self.requests),1)
        self.assertEqual(sum(g['status']=='skipped' for g in result['games']),5)

    def test_defaults_disabled_and_budget_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=root/'data/test.db';initialize_database(db)
            h=HistorySync(root,db,self.games,mode_provider=lambda:self.mode)
            self.assertFalse(h.settings()['enabled'])
            self.assertEqual(h.run()['status'],'disabled')
        for n in (0,6,True):
            with self.assertRaises(ValueError):self.h.configure({**DEFAULTS,'max_pages':n})
            with self.assertRaises(ValueError):self.run_scan(max_pages=n)

    def test_timeout_partial_commit_then_recovery(self):
        self.overrides[(8552,2)]=httpx.ReadTimeout('offline')
        result=self.run_scan();self.assertEqual(result['status'],'partial')
        self.assertEqual(self.h.committed()['8552']['page'],1);self.assertEqual(self.count('mods'),2)
        self.overrides.clear();self.next_day();self.run_scan();self.assertEqual(self.count('mods'),4)

    def test_retries_are_inside_hard_request_budget(self):
        attempts=0
        def temporary(request):
            nonlocal attempts
            attempts+=1
            if attempts==1:raise httpx.ConnectTimeout('temporary')
            return httpx.Response(200,json={'_aRecords':[self.record(8,8552),self.record(7,8552)],'_aMetadata':{'_nPerpage':2,'_nRecordCount':8}})
        self.overrides[(8552,1)]=temporary
        result=self.run_scan();self.assertEqual(result['requests'],2);self.assertEqual(len(self.requests),2)
        self.assertEqual(self.h.committed()['8552']['page'],1)

    def test_write_or_backup_failure_no_checkpoint(self):
        with patch('history_sync.verified_backup',side_effect=OSError('backup failure')):
            self.assertEqual(self.run_scan()['status'],'failed')
        self.assertFalse(self.h.committed());self.assertEqual(self.count('mods'),0)
        self.next_day();c=connect_database(self.db)
        c.execute("CREATE TRIGGER reject_event BEFORE INSERT ON mod_events BEGIN SELECT RAISE(ABORT,'reject'); END");c.commit();c.close()
        self.assertEqual(self.run_scan()['status'],'failed');self.assertEqual(self.count('mods'),0)
        self.assertFalse(self.h.committed());self.assertEqual(self.count('sync_runs'),0)

    def test_interrupt_does_not_advance_and_can_resume(self):
        self.overrides[(8552,2)]=KeyboardInterrupt()
        self.assertEqual(self.run_scan()['status'],'stopped');self.assertFalse(self.h.committed())
        self.overrides.clear();self.next_day();self.run_scan();self.assertEqual(self.count('mods'),4)

    def test_ctrl_c_inside_transaction_rolls_back(self):
        with patch('history_sync.verified_backup',side_effect=KeyboardInterrupt()):
            self.assertEqual(self.run_scan()['status'],'stopped')
        self.assertEqual(self.count('mods'),0);self.assertFalse(self.h.committed())

    def test_shared_lock_and_manual_preview_protection(self):
        with instance_lock(self.root/'logs/content_ratings/instance.lock'):
            with self.assertRaises(RuntimeError):self.run_scan()
        service=WebSync(self.db,self.root,self.games);service.state={'status':'waiting'}
        service.candidate={'created':self.now,'snapshots':[]};service.save()
        before=service.path.read_bytes();self.assertEqual(self.run_scan()['status'],'manual_preview_pending')
        self.assertEqual(before,service.path.read_bytes());self.assertFalse(self.requests)

    def test_check_and_explicit_dry_run_no_database_or_progress(self):
        self.mode['mode']='check';before=self.db.read_bytes();self.run_scan()
        self.assertEqual(self.db.read_bytes(),before);self.assertFalse(self.h.committed())
        self.assertFalse((self.db.parent/'backups').exists())
        state=(self.h.directory/'state.json').read_bytes();self.run_scan(dry_run=True)
        self.assertEqual((self.h.directory/'state.json').read_bytes(),state)
        self.assertEqual(self.db.read_bytes(),before)

    def test_newer_values_and_user_images_follow_ratings_survive(self):
        self.run_scan();c=connect_database(self.db)
        images=json.dumps([{'image_url':'https://images.gamebanana.com/img/ss/mods/original.jpg','original_verified':True}])
        c.execute("UPDATE mods SET title='Newer title',updated_at='2025-01-01T00:00:00Z',preview_urls_json=?,raw_metadata_json=? WHERE item_id=6",(images,json.dumps({'_source_rating_evidence':{'fields':{'_aContentRatings':{'pn':'Partial Nudity'}},'observed_at':'2025-01-01T00:00:00Z'}})))
        c.execute("UPDATE user_states SET is_read=1,is_favorite=1,note='keep'")
        c.execute("INSERT INTO author_subscriptions VALUES('gamebanana',7,'Author','2025-01-01T00:00:00Z')");c.commit()
        states=[tuple(r) for r in c.execute('SELECT * FROM user_states ORDER BY item_id')]
        first=c.execute('SELECT first_seen_at FROM mods WHERE item_id=6').fetchone()[0];c.close()
        self.next_day();self.run_scan();c=connect_database(self.db)
        try:
            row=c.execute('SELECT * FROM mods WHERE item_id=6').fetchone()
            self.assertEqual(row['title'],'Newer title');self.assertEqual(row['updated_at'],'2025-01-01T00:00:00Z')
            self.assertEqual(json.loads(row['preview_urls_json']),json.loads(images))
            self.assertEqual(row['first_seen_at'],first)
            self.assertIn('_source_rating_evidence',json.loads(row['raw_metadata_json']))
            self.assertEqual(states,[tuple(r) for r in c.execute('SELECT * FROM user_states WHERE item_id IN (5,6,7,8) ORDER BY item_id')])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM author_subscriptions').fetchone()[0],1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM mod_events WHERE event_type='source_updated'").fetchone()[0],0)
        finally:c.close()

    def test_disabled_history_default_and_auto_interval_independent(self):
        disabled=HistorySync(self.root/'missing',self.root/'missing/data/eryoutoolbox.db',self.games,mode_provider=lambda:self.mode)
        with self.assertRaises(ValueError):disabled.run()
        self.assertFalse(disabled.database.exists())
        auto=AutoSync(self.root,self.db,self.games,state_dir=self.root/'device')
        auto.configure({**AUTO_DEFAULTS,'mode':'check'})
        # A daily task not due can still dispatch due history, without another lock.
        from auto_sync import atomic_json
        atomic_json(auto.directory/'last_run.json',{'status':'success','started_epoch':self.now,'started_at':'2026-01-01T00:00:00Z'})
        client=self.client()
        with patch('history_sync.httpx.Client',return_value=client):
            result=auto.run()
        self.assertEqual(result['status'],'not_due');self.assertEqual(result['history']['requests'],12)
        self.assertEqual(self.count('mods'),0)

    def test_checkpoint_recovers_after_mirror_write_failure(self):
        from history_sync import atomic_json as real
        def fail(path,value):
            if path.name=='state.json' and value['games'].get('8552',{}).get('checkpoint'):raise OSError('disk mirror failed')
            return real(path,value)
        with patch('history_sync.atomic_json',side_effect=fail):
            with self.assertRaises(OSError):self.run_scan()
        self.assertEqual(self.h.committed()['8552']['page'],2);self.assertEqual(self.count('mods'),4)

    def test_reliable_updated_time_only_generates_source_update(self):
        self.run_scan();c=connect_database(self.db)
        c.execute("UPDATE mods SET updated_at='2023-01-01T00:00:00Z',raw_metadata_json=? WHERE item_id=6",(json.dumps({'_snapshot_collected_at':'2024-01-01T00:00:00Z'}),));c.commit();c.close()
        self.row_changes[6]={'_tsDateUpdated':1_735_689_600}
        self.next_day();result=self.run_scan()
        self.assertEqual(result['games'][0]['source_updates'],1)
        c=connect_database(self.db)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM mod_events WHERE event_type='source_updated'").fetchone()[0],1);c.close()

    def test_disable_before_commit_is_rejected(self):
        def disable(request):
            self.mode['mode']='off'
            return httpx.Response(200,json={'_aRecords':[self.record(6,8552),self.record(5,8552)],'_aMetadata':{'_nPerpage':2,'_nRecordCount':8}})
        self.overrides[(8552,2)]=disable
        self.assertEqual(self.run_scan()['status'],'failed');self.assertFalse(self.h.committed());self.assertEqual(self.count('mods'),0)

    def test_missing_source_version_times_only_fill_missing_fields(self):
        self.run_scan();c=connect_database(self.db)
        c.execute("UPDATE mods SET title='Keep newer title',version='2',modified_at=NULL,updated_at=NULL,raw_metadata_json=? WHERE item_id=6",(json.dumps({'_snapshot_collected_at':'2024-01-01T00:00:00Z'}),));c.commit();c.close()
        self.row_changes[6]={'_sVersion':'1','_aSubmitter':{'_idRow':7,'_sName':'Author','_sProfileUrl':'https://gamebanana.com/members/7'}}
        self.next_day();self.run_scan();c=connect_database(self.db)
        try:
            row=c.execute('SELECT title,version,author_url FROM mods WHERE item_id=6').fetchone()
            self.assertEqual(tuple(row),('Keep newer title','2','https://gamebanana.com/members/7'))
        finally:c.close()

    def test_history_http_origin_settings_and_read_only_status(self):
        from http.client import HTTPConnection
        from http.server import ThreadingHTTPServer
        import threading
        from react_api import ReadOnlyAPI,make_handler
        api=ReadOnlyAPI(self.db)
        api.auto_sync=AutoSync(self.root,self.db,self.games,state_dir=self.root/'device')
        api.auto_sync.configure({**AUTO_DEFAULTS,'mode':'check'})
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(api,0));port=server.server_address[1]
        server.RequestHandlerClass=make_handler(api,port)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        headers={'Origin':'http://127.0.0.1:5173','Content-Type':'application/json','X-ErYouToolbox':'1'}
        try:
            connection=HTTPConnection('127.0.0.1',port,timeout=5)
            connection.request('GET','/api/history-sync');response=connection.getresponse();value=json.loads(response.read());self.assertEqual(response.status,200);self.assertTrue(value['settings']['enabled'])
            body=json.dumps({'action':'configure','settings':{**DEFAULTS,'enabled':False}})
            connection.request('POST','/api/history-sync',body,{**headers,'Origin':'https://other.example'});response=connection.getresponse();response.read();self.assertEqual(response.status,403)
            connection.request('POST','/api/history-sync',body,headers);response=connection.getresponse();response.read();self.assertEqual(response.status,200)
            self.assertFalse(self.h.settings()['enabled']);self.assertEqual(api.auto_sync.settings()['mode'],'check')
            connection.request('POST','/api/history-sync','{"action":"sql"}',headers);response=connection.getresponse();response.read();self.assertEqual(response.status,400)
            connection.close();self.assertEqual(self.count('mods'),0);self.assertEqual(self.count('sync_runs'),0)
        finally:server.shutdown();server.server_close();worker.join(timeout=5)


if __name__=='__main__':unittest.main()
