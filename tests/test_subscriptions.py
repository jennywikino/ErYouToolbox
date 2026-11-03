import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eryoutoolbox.database import initialize_database, MIGRATIONS
from eryoutoolbox.subscriptions import set_follow, status, migrate
from eryoutoolbox.ui_queries import query_mods
from react_api import valid_write_origin

class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT)
        self.db=Path(self.temp.name)/'data.db'
        initialize_database(self.db)
        c=sqlite3.connect(self.db)
        for source,item,game,author in [('gamebanana',1,8552,7),('gamebanana',2,19567,7),('other',3,8552,7)]:
            c.execute('INSERT INTO mods(source,item_type,item_id,game_id,author_id,author_name,raw_metadata_json,preview_urls_json,created_at,updated_at,first_seen_at,last_checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (source,'Mod',item,game,author,'Author',json.dumps({'_aContentRatings':{'pn':'Partial Nudity'}}),'["https://example.org/full.jpg"]','2026-01-01','2026-10-29','2026-01-01','2026-01-01'))
        c.execute("INSERT INTO user_states(source,item_type,item_id,note,updated_at) VALUES('gamebanana','Mod',1,'private note','now')")
        c.commit();c.close()
    def tearDown(self):self.temp.cleanup()
    def test_follow_duplicate_unfollow_and_reopen(self):
        self.assertTrue(set_follow(self.db,'gamebanana',7,True)['changed'])
        self.assertTrue(status(self.db,'gamebanana',7)['followed'])
        self.assertFalse(set_follow(self.db,'gamebanana',7,True,backup=lambda:self.fail('duplicate backup'))['changed'])
        self.assertTrue(set_follow(self.db,'gamebanana',7,False)['changed'])
        self.assertFalse(status(self.db,'gamebanana',7)['followed'])
    def test_invalid_and_nonlocal_author(self):
        for value in (None,0,-1,True,'7',2**64):
            with self.assertRaises(ValueError):set_follow(self.db,'gamebanana',value,True)
        with self.assertRaises(ValueError):set_follow(self.db,'gamebanana',999,True)
    def test_cross_game_and_source_identity(self):
        set_follow(self.db,'gamebanana',7,True)
        rows=query_mods(self.db,subscriptions_only=True)['items']
        self.assertEqual({r['item_id'] for r in rows},{1,2})
        self.assertFalse(status(self.db,'other',7)['followed'])
        set_follow(self.db,'other',7,True)
        self.assertEqual(query_mods(self.db,subscriptions_only=True)['total_count'],3)
    def test_filters_and_pagination(self):
        set_follow(self.db,'gamebanana',7,True)
        self.assertEqual(query_mods(self.db,subscriptions_only=True,game_id=19567,rating_codes=['pn'])['total_count'],1)
        self.assertEqual(query_mods(self.db,subscriptions_only=True,rating_codes=['sc'])['total_count'],2)
        a=query_mods(self.db,subscriptions_only=True,limit=1)['items']
        b=query_mods(self.db,subscriptions_only=True,limit=1,offset=1)['items']
        self.assertNotEqual(a[0]['item_id'],b[0]['item_id'])
    def test_updated_feed_requires_source_event(self):
        set_follow(self.db,'gamebanana',7,True)
        self.assertEqual(query_mods(self.db,subscriptions_only=True,require_updated=True)['total_count'],0)
        c=sqlite3.connect(self.db)
        c.execute("INSERT INTO mod_events(source,item_type,item_id,event_type,detected_at) VALUES('gamebanana','Mod',1,'metadata_changed','now')")
        c.commit();c.close()
        self.assertEqual(query_mods(self.db,subscriptions_only=True,require_updated=True)['total_count'],0)
        c=sqlite3.connect(self.db)
        c.execute("INSERT INTO mod_events(source,item_type,item_id,event_type,detected_at) VALUES('gamebanana','Mod',1,'source_updated','2026-10-29')")
        c.commit();c.close()
        self.assertEqual(query_mods(self.db,subscriptions_only=True,require_updated=True)['total_count'],1)
    def test_no_metadata_or_user_state_changes(self):
        c=sqlite3.connect(self.db);before=c.execute('SELECT * FROM mods').fetchall();state=c.execute('SELECT * FROM user_states').fetchall();c.close()
        set_follow(self.db,'gamebanana',7,True)
        c=sqlite3.connect(self.db)
        self.assertEqual(before,c.execute('SELECT * FROM mods').fetchall())
        self.assertEqual(state,c.execute('SELECT * FROM user_states').fetchall());c.close()
    def legacy(self):
        c=sqlite3.connect(self.db);c.execute('ALTER TABLE user_states DROP COLUMN first_viewed_at');c.commit();c.close()
        c=sqlite3.connect(self.db);c.execute('DROP TABLE author_subscriptions');c.execute('PRAGMA user_version=1');c.commit();c.close()
    def test_explicit_migration_backup_and_idempotence(self):
        self.legacy()
        with self.assertRaises(RuntimeError):initialize_database(self.db)
        migrate(self.db)
        self.assertTrue(status(self.db,'gamebanana',7)['available'])
        count=len(list((self.db.parent/'backups').glob('*.db')))
        migrate(self.db)
        self.assertEqual(len(list((self.db.parent/'backups').glob('*.db'))),count)
    def test_migration_rollback(self):
        self.legacy()
        with patch.dict(MIGRATIONS,{2:MIGRATIONS[2]+('INVALID SQL',)}):
            with self.assertRaises(sqlite3.Error):migrate(self.db)
        c=sqlite3.connect(self.db)
        self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],1)
        self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='author_subscriptions'").fetchone())
        self.assertEqual(c.execute('SELECT COUNT(*) FROM mods').fetchone()[0],3);c.close()
    def test_backup_failure_prevents_write_and_migration(self):
        with self.assertRaises(OSError):set_follow(self.db,'gamebanana',7,True,backup=lambda:(_ for _ in ()).throw(OSError('failed')))
        self.assertFalse(status(self.db,'gamebanana',7)['followed'])
        self.legacy()
        with patch('eryoutoolbox.subscriptions.verified_backup',side_effect=OSError('failed')):
            with self.assertRaises(OSError):migrate(self.db)
    def test_empty_and_unmigrated_read_only(self):
        self.legacy();before=hashlib.sha256(self.db.read_bytes()).digest()
        self.assertFalse(status(self.db,'gamebanana',7)['available'])
        self.assertEqual(query_mods(self.db,subscriptions_only=True)['total_count'],0)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).digest(),before)
    def test_origin_guards(self):
        headers={'Host':'127.0.0.1:8766','Origin':'http://127.0.0.1:5173','Content-Type':'application/json','X-ErYouToolbox':'1'}
        self.assertTrue(valid_write_origin(headers,8766))
        for key,value in [('Host','evil.test'),('Origin','http://evil.test'),('Origin','null'),('Content-Type','text/plain'),('X-ErYouToolbox','')]:
            self.assertFalse(valid_write_origin({**headers,key:value},8766))

    def test_http_post_guard_and_follow_round_trip(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from http.client import HTTPConnection
        from react_api import ReadOnlyAPI, make_handler
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(ReadOnlyAPI(self.db),8766))
        port=server.server_port
        server.RequestHandlerClass=make_handler(ReadOnlyAPI(self.db),port)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            body=json.dumps({'source':'gamebanana','author_id':7,'followed':True})
            for origin,expected in [('http://evil.test',403),('http://127.0.0.1:5173',200)]:
                client=HTTPConnection('127.0.0.1',port,timeout=5)
                client.request('POST','/api/subscription',body,{'Origin':origin,'Content-Type':'application/json','X-ErYouToolbox':'1'})
                response=client.getresponse();response.read()
                self.assertEqual(response.status,expected);client.close()
            self.assertTrue(status(self.db,'gamebanana',7)['followed'])
            client=HTTPConnection('127.0.0.1',port,timeout=5)
            client.request('POST','/api/read-state',json.dumps({'source':'gamebanana','item_id':1,'is_read':True}),{'Origin':'http://127.0.0.1:5173','Content-Type':'application/json','X-ErYouToolbox':'1'})
            response=client.getresponse();saved=json.loads(response.read());client.close()
            self.assertEqual(response.status,200);self.assertTrue(saved['is_read']);self.assertTrue(saved['first_viewed_at'])
        finally:
            server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
