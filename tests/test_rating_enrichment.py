"""Bounded desktop rating path; only temporary databases and simulated HTTP."""
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eryoutoolbox.database import initialize_database,backup_database
from eryoutoolbox.content_ratings import source_ratings,save_verified_samples,preview_allowed
from rating_enrichment import RatingEnrichment
from backfill_content_ratings import instance_lock
from react_api import ReadOnlyAPI


def response(url,fields=None,status=200,headers=None):
    item_id=int(url.split('/')[-2])
    return httpx.Response(status,json={'_idRow':item_id,**(fields if fields is not None else {'_aContentRatings':{'pn':'Partial Nudity','nu':'Full Nudity'}})},headers=headers,request=httpx.Request('GET',url))


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'data/eryoutoolbox.db'
        initialize_database(self.db)
        with closing(sqlite3.connect(self.db)) as c:
            for i,raw in [(1,{'manual_review':'keep'}),(2,{'_record':{'has_content_ratings':False}}),(3,{'_source_rating_evidence':{'observed_at':'2026-01-01T00:00:00Z','fields':{'_aContentRatings':{'sc':'Sexual Content'}}}})]:
                c.execute("INSERT INTO mods(source,item_type,item_id,game_id,preview_urls_json,raw_metadata_json,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',?,8552,'[\"https://example.com/a.jpg\"]',?,'2026-01-01','2026-01-01')",(i,json.dumps(raw)))
            c.execute("INSERT INTO user_states(source,item_type,item_id,is_read,is_favorite,note,updated_at) VALUES('gamebanana','Mod',1,1,1,'keep','2026-01-01')")
            c.execute("INSERT INTO author_subscriptions VALUES('gamebanana',7,'keep','2026-01-01')")
            c.commit()
        self.service=RatingEnrichment(self.db,self.root);self.client=Mock();self.client.get.side_effect=lambda url:response(url)

    def tearDown(self):self.tmp.cleanup()

    def run_batch(self,**kwargs):
        with patch('backfill_content_ratings.time.sleep'):
            return self.service.execute(client=self.client,limit=20,**kwargs)

    def rating(self):
        with closing(sqlite3.connect(self.db)) as c:return source_ratings(c.execute('SELECT raw_metadata_json FROM mods WHERE item_id=1').fetchone()[0])

    def test_parse_single_multi_unrated_unknown(self):
        for fields,codes in [({'_aContentRatings':{'pn':'Partial Nudity'}},['pn']),({'_aContentRatings':{'pn':'Partial Nudity','sc':'Sexual Content'}},['pn','sc']),({'_bHasContentRatings':False},['-']),({'_bHasContentRatings':True},['UNKNOWN']),({},['UNKNOWN']),({'_aContentRatings':{},'_bHasContentRatings':True},['UNKNOWN']),({'_aContentRatings':{'':'invalid'}},['UNKNOWN'])]:
            self.assertEqual(source_ratings(fields)['codes'],codes)

    def test_dry_run_has_no_database_checkpoint_or_backup_effect(self):
        before=hashlib.sha256(self.db.read_bytes()).digest();report=self.run_batch()
        self.assertEqual(report['batches'][0]['save']['candidates'],1);self.assertEqual(report['totals']['requests'],1)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).digest(),before)
        self.assertFalse((self.service.directory/'checkpoint_all.json').exists());self.assertFalse((self.db.parent/'backups').exists())

    def test_apply_persists_and_is_idempotent_and_protects_other_fields(self):
        with closing(sqlite3.connect(self.db)) as c:
            before=[tuple(r) for r in c.execute('SELECT preview_urls_json,content_rating_status,title,author_name,first_seen_at,last_checked_at FROM mods')]
            states=[tuple(r) for r in c.execute('SELECT * FROM user_states')]
            follows=[tuple(r) for r in c.execute('SELECT * FROM author_subscriptions')]
        self.assertEqual(self.run_batch(apply=True)['totals']['updated'],1)
        self.assertEqual(self.rating()['codes'],['pn','nu']);self.assertTrue(self.rating()['observed_at'])
        self.assertTrue(list((self.db.parent/'backups').glob('*.db')))
        self.service=RatingEnrichment(self.db,self.root);self.client.reset_mock()
        self.assertEqual(self.run_batch(apply=True)['totals']['updated'],0);self.client.get.assert_not_called()
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(before,[tuple(r) for r in c.execute('SELECT preview_urls_json,content_rating_status,title,author_name,first_seen_at,last_checked_at FROM mods')])
            self.assertEqual(states,[tuple(r) for r in c.execute('SELECT * FROM user_states')]);self.assertEqual(follows,[tuple(r) for r in c.execute('SELECT * FROM author_subscriptions')])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mod_events').fetchone()[0],0);self.assertEqual(c.execute('SELECT COUNT(*) FROM sync_runs').fetchone()[0],0)
            self.assertEqual(json.loads(c.execute('SELECT raw_metadata_json FROM mods WHERE item_id=1').fetchone()[0])['manual_review'],'keep')

    def test_missing_source_fields_remain_unknown_and_retry_survives_restart(self):
        self.client.get.side_effect=lambda url:response(url,{'_sInitialVisibility':'show'})
        self.assertEqual(self.run_batch(apply=True)['status'],'failed');self.assertEqual(self.rating()['codes'],['UNKNOWN'])
        checkpoint=json.loads((self.service.directory/'checkpoint_all.json').read_text())
        self.assertEqual(checkpoint['attempted_ids'],[]);self.assertIn('1',checkpoint['failures'])
        self.service=RatingEnrichment(self.db,self.root);self.client.get.side_effect=lambda url:response(url)
        self.assertEqual(self.run_batch(apply=True,retry_failed=True)['totals']['updated'],1)

    def test_403_404_429_do_not_become_unrated(self):
        for status in (403,404,429):
            with self.subTest(status=status):
                self.client.get.side_effect=lambda url:response(url,status=status,headers={'Retry-After':'30'})
                report=self.run_batch();self.assertEqual(report['totals']['failed'],1)
                self.assertEqual(self.rating()['codes'],['UNKNOWN']);self.assertEqual(report['totals']['requests'],1)
                if status in (403,429):
                    self.assertTrue(report['not_before'])
                    again=self.run_batch();self.assertEqual(again['totals']['requests'],0)
                    (self.service.directory/'source_pause.json').unlink()

    def test_timeout_and_invalid_json_keep_database_unchanged(self):
        for failure in (httpx.ReadTimeout('timeout'),ValueError('Invalid JSON')):
            self.client.get.side_effect=failure
            report=self.run_batch();self.assertEqual(report['totals']['failed'],1);self.assertEqual(self.rating()['codes'],['UNKNOWN'])

    def test_backup_failure_and_sqlite_failure_roll_back(self):
        with patch('rating_enrichment.backup_database',side_effect=OSError('backup failed')):
            self.assertEqual(self.run_batch(apply=True)['status'],'failed')
        self.assertEqual(self.rating()['codes'],['UNKNOWN'])
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("CREATE TRIGGER fail_rating BEFORE UPDATE OF raw_metadata_json ON mods BEGIN SELECT RAISE(ABORT,'fail'); END");c.commit()
        self.assertEqual(self.run_batch(apply=True)['status'],'failed');self.assertEqual(self.rating()['codes'],['UNKNOWN'])
        self.assertFalse((self.service.directory/'checkpoint_all.json').exists())

    def test_shared_lock_and_cancel_prevent_requests(self):
        with instance_lock(self.service.directory/'instance.lock'):
            self.assertEqual(self.run_batch()['totals']['requests'],0)
        self.service.cancel.set();self.assertEqual(self.run_batch()['status'],'stopped')
        self.client.get.assert_not_called()

    def test_invalid_actions_and_batch_limit(self):
        for body in ({'action':'run','limit':21},{'action':'run','apply':'yes'},{'action':'run','ids':[1]},{'action':'delete'}):
            with self.assertRaises(ValueError):self.service.start(body)

    def test_older_evidence_cannot_replace_newer_and_filter_is_or(self):
        self.run_batch(apply=True)
        report={'format':'eryoutoolbox-rating-audit-v1','observed_at':'2020-01-01T00:00:00Z','samples':[{'source':'gamebanana','item_type':'Mod','item_id':1,'http_status':200,'detail':{'_bHasContentRatings':False}}]}
        with closing(sqlite3.connect(self.db)) as c:self.assertEqual(save_verified_samples(c,report)['candidates'],0)
        api=ReadOnlyAPI(self.db,runtime_root=self.root)
        self.assertEqual(api.get('/api/mods?ratings=pn,sc')[1]['total_count'],2)
        self.assertEqual(api.get('/api/mods?ratings=-')[1]['total_count'],1)
        self.assertEqual(api.get('/api/mods?ratings=UNKNOWN')[1]['total_count'],0)

    def test_conservative_image_policy_and_explicit_preferences(self):
        risky={'source_ratings':{'codes':['pn']},'content_rating_status':'UNKNOWN'}
        unknown={'source_ratings':{'codes':['UNKNOWN']}}
        unrated={'source_ratings':{'codes':['-']}}
        self.assertFalse(preview_allowed(risky,True));self.assertTrue(preview_allowed(risky,True,True))
        self.assertFalse(preview_allowed(unknown,True));self.assertTrue(preview_allowed(unknown,True,False,True))
        self.assertTrue(preview_allowed(unrated,True));self.assertFalse(preview_allowed(unrated,False))
        self.assertFalse(preview_allowed({'source_ratings':{'codes':['st','rp']}},True))
        self.assertTrue(preview_allowed({'source_ratings':{'codes':['rp']}},True,False,True))

    def test_http_origin_busy_task_and_success(self):
        from desktop_app import create_server
        server,api,_=create_server(self.root,self.db)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        entered=threading.Event();release=threading.Event()
        def get(url):entered.set();release.wait(5);return response(url)
        self.client.get.side_effect=get
        def request(body=None,origin=None):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            headers={'Origin':origin or f'http://127.0.0.1:{server.server_port}','Content-Type':'application/json','X-ErYouToolbox':'1'}
            try:
                c.request('POST' if body is not None else 'GET','/api/rating-enrichment',json.dumps(body) if body is not None else None,headers)
                r=c.getresponse();raw=r.read();return r.status,json.loads(raw) if r.status!=403 else None
            finally:c.close()
        try:
            with patch('rating_enrichment.httpx.Client') as factory:
                factory.return_value.__enter__.return_value=self.client
                self.assertEqual(request({'action':'run'},origin='https://evil.example')[0],403)
                self.assertEqual(request({'action':'run','apply':True})[0],200);self.assertTrue(entered.wait(3))
                self.assertEqual(request({'action':'run'})[0],400)
                release.set()
                for _ in range(300):
                    status,value=request()
                    if not value['running']:break
                    time.sleep(.01)
                self.assertFalse(value['running']);self.assertEqual(value['totals']['updated'],1)
        finally:
            release.set();server.shutdown();server.server_close();thread.join()

    def test_newer_detail_evidence_replaces_old_and_survives_reopen(self):
        self.run_batch(apply=True)
        report={'format':'eryoutoolbox-rating-audit-v1','observed_at':'2099-01-01T00:00:00Z','samples':[{'source':'gamebanana','item_type':'Mod','item_id':1,'http_status':200,'detail':{'_aContentRatings':{'sc':'Sexual Content'}}}]}
        with closing(sqlite3.connect(self.db)) as c:
            saved=save_verified_samples(c,report,dry_run=False,before_write=lambda:backup_database(self.db,self.root/'newer-backup.db'))
        self.assertEqual(saved['updated'],1);self.assertEqual(self.rating()['codes'],['sc'])
