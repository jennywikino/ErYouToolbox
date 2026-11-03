"""Desktop tests only use fresh temporary portable data."""
import http.client
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'src'))
from desktop_app import prepare_data, create_server
from backfill_content_ratings import instance_lock


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.home=Path(self.temp.name)/'portable'
        self.root,self.db=prepare_data(self.home)
        self.static=Path(self.temp.name)/'static'
        (self.static/'assets').mkdir(parents=True)
        (self.static/'index.html').write_text('<html>Production</html>')
        (self.static/'assets/app.js').write_text('test')
        self.server,self.api,self.closing=create_server(self.root,self.db,self.static)
        self.thread=threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.temp.cleanup()

    def request(self,path,body=None,origin=None,host=None):
        port=self.server.server_port
        c=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        headers={'Host':host or f'127.0.0.1:{port}'}
        if body is not None:headers.update({'Origin':origin or f'http://127.0.0.1:{port}','Content-Type':'application/json','X-ErYouToolbox':'1'})
        c.request('GET' if body is None else 'POST',path,json.dumps(body) if body is not None else None,headers)
        r=c.getresponse();raw=r.read();status=r.status;c.close()
        return status,raw

    def seed(self):
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("INSERT INTO mods(source,item_type,item_id,game_id,author_id,author_name,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',1,8552,7,'Author','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")
            c.commit()

    def test_empty_schema_and_six_games(self):
        self.assertEqual(len(json.loads(self.request('/api/games')[1])['games']),6)
        self.assertEqual(json.loads(self.request('/api/mods')[1])['total_count'],0)
        self.assertEqual(self.api.auto_sync.settings()['mode'],'off')

    def test_static_allowlist(self):
        self.assertEqual(self.request('/')[0],200)
        self.assertEqual(self.request('/assets/app.js')[0],200)
        for path in ['/data/eryoutoolbox.db','/config/project_identity.json','/assets/../../userdata/portable.json','/assets/%2e%2e/%2e%2e/README.md','/logs/test']:
            self.assertEqual(self.request(path)[0],404,path)

    def test_origin_and_host(self):
        self.assertEqual(self.request('/api/games',host='evil.example')[0],403)
        self.assertEqual(self.request('/api/read-state',{},origin='http://127.0.0.1:5173')[0],403)
        self.assertEqual(self.request('/api/read-state',{},origin='https://evil.example')[0],403)

    def test_read_follow_persist(self):
        self.seed()
        self.assertEqual(self.request('/api/read-state',{'source':'gamebanana','item_id':1,'is_read':True})[0],200)
        self.assertEqual(self.request('/api/subscription',{'source':'gamebanana','author_id':7,'followed':True})[0],200)
        _,db=prepare_data(self.home)
        with closing(sqlite3.connect(db)) as c:
            self.assertEqual(c.execute('SELECT is_read FROM user_states').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM author_subscriptions').fetchone()[0],1)
        self.assertTrue(list((db.parent/'backups').glob('*.db')))

    def test_closing_rejects_writes(self):
        self.closing.set()
        self.assertEqual(self.request('/api/read-state',{})[0],503)

    def test_missing_db_not_recreated(self):
        self.db.unlink()
        with self.assertRaisesRegex(ValueError,'missing'):prepare_data(self.home)
        self.assertFalse(self.db.exists())

    def test_unknown_data_refused(self):
        home=Path(self.temp.name)/'unknown'
        (home/'userdata').mkdir(parents=True)
        (home/'userdata/private.json').write_text('{}')
        with self.assertRaises(ValueError):prepare_data(home)
        self.assertFalse((home/'userdata/data/eryoutoolbox.db').exists())

    def test_portable_move_and_update(self):
        self.seed()
        moved=Path(self.temp.name)/'other-drive'
        shutil.copytree(self.home,moved)
        _,db=prepare_data(moved)
        with closing(sqlite3.connect(db)) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM mods').fetchone()[0],1)
        original=db.read_bytes()
        (moved/'ErYouToolbox.exe').write_bytes(b'new-version')
        prepare_data(moved)
        self.assertEqual(original,db.read_bytes())

    def test_instance_lock(self):
        with instance_lock(self.home/'.desktop.lock'):
            with self.assertRaises(RuntimeError):
                with instance_lock(self.home/'.desktop.lock'):pass

    def test_dynamic_port(self):
        other,_,_=create_server(self.root,self.db,self.static)
        try:self.assertNotEqual(other.server_port,self.server.server_port)
        finally:other.server_close()

    def test_scheduler_unsupported(self):
        result=json.loads(self.request('/api/auto-sync')[1])
        self.assertEqual(result['task']['status'],'unsupported')
        self.assertFalse(result['task']['registered'])

    def test_runtime_and_disabled_startup(self):
        self.assertEqual(self.api.web_sync.root,self.root)
        self.assertEqual(self.api.auto_sync.root,self.root)
        self.assertTrue(self.api.auto_sync.directory.is_relative_to(self.root))
        self.assertEqual(self.request('/api/auto-sync/startup',{})[0],200)
        self.assertEqual(self.api.auto_sync.settings()['mode'],'off')

    def test_frozen_api_does_not_require_development_config(self):
        import react_api
        with patch.object(react_api,'ROOT',Path(self.temp.name)/'no-development-source'):
            from react_api import ReadOnlyAPI
            api=ReadOnlyAPI(self.db,self.root/'config/games.json',runtime_root=self.root)
            self.assertEqual(api.get('/api/content-ratings')[0],410)

    def test_unwritable_data_fails_without_fallback(self):
        with patch('desktop_app.Path.open',side_effect=PermissionError('Read only')):
            with self.assertRaises(PermissionError):prepare_data(Path(self.temp.name)/'readonly')
        self.assertFalse((Path(self.temp.name)/'readonly/userdata/data/eryoutoolbox.db').exists())

    def test_unsupported_schema_preserved(self):
        with closing(sqlite3.connect(self.db)) as c:
            c.execute('PRAGMA user_version=999')
        original=self.db.read_bytes()
        with self.assertRaisesRegex(ValueError,'migration'):prepare_data(self.home)
        self.assertEqual(self.db.read_bytes(),original)

    def test_http_sync_preview_confirm_repeat(self):
        sample={'collected_at':'2026-11-03T00:00:00Z','records':[{'source':'gamebanana','item_type':'Mod','item_id':21,'game_id':8552,'title':'Fixture','created_at':'2026-11-02T00:00:00Z'}], 'failure_reasons':[],'actual_record_count':1,'request_count':1}
        def wait():
            for _ in range(300):
                state=json.loads(self.request('/api/sync')[1])
                if state['status'] not in ('checking','importing'):return state
                time.sleep(.01)
            self.fail('Desktop task did not finish')
        with patch('web_sync.collect_game',return_value=sample),patch('web_sync.time.sleep'):
            for _ in range(2):
                self.assertEqual(self.request('/api/sync',{'action':'check','game':8552,'max_pages':1})[0],200)
                state=wait()
                self.assertEqual(state['status'],'waiting')
                self.assertEqual(self.request('/api/sync',{'action':'confirm','game':8552,'token':state['token']})[0],200)
                final=wait()
                self.assertEqual(final['status'],'success',json.dumps(final))
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mods').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mod_events').fetchone()[0],1)

    def test_preview_is_not_confirmable_until_worker_releases_lock(self):
        self.api.web_sync.state={'status':'waiting','token':'test'}
        self.api.web_sync.worker_active=True
        try:
            self.assertEqual(json.loads(self.request('/api/sync')[1])['status'],'checking')
            self.assertEqual(self.request('/api/sync',{'action':'confirm','game':8552,'token':'test'})[0],409)
        finally:self.api.web_sync.worker_active=False
        self.assertEqual(json.loads(self.request('/api/sync')[1])['status'],'waiting')
