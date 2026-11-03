"""Real HTTP/temporary SQLite lifecycle tests; no production/source requests."""
from contextlib import closing
import json
import socket
import sqlite3
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_desktop as desktop_tests
from desktop_lifecycle import DesktopLifecycle


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        self.fixture=desktop_tests.DesktopTests('test_empty_schema_and_six_games');self.fixture.setUp()
        f=self.fixture
        self.life=DesktopLifecycle(f.server,f.api,f.closing,f.thread,f.root,wait_seconds=8)
        self.destroyed=threading.Event()
        def destroy():
            self.assertTrue(self.life.before_close())
            self.destroyed.set()
        self.life.window=SimpleNamespace(destroy=destroy)

    def tearDown(self):
        if self.life.worker:self.life.worker.join(timeout=10)
        self.fixture.tearDown()

    def finish(self):
        self.assertTrue(self.destroyed.wait(10),'Close did not finish')
        self.life.finish()
        self.assertFalse(self.fixture.thread.is_alive())
        with socket.socket() as sock:
            self.assertNotEqual(sock.connect_ex(self.fixture.server.server_address),0)
        with closing(sqlite3.connect(self.fixture.db)) as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertFalse(self.life.worker.is_alive())

    def test_idle_and_list_then_close(self):
        self.assertEqual(self.fixture.request('/api/mods')[0],200)
        self.assertFalse(self.life.before_close());self.finish()

    def test_partial_post_cannot_block_gui_close(self):
        f=self.fixture;port=f.server.server_port
        with socket.create_connection(('127.0.0.1',port)) as client:
            client.sendall((f'POST /api/sync HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\nX-ErYouToolbox: 1\r\nContent-Length: 100\r\n\r\n{{').encode())
            time.sleep(.1)
            start=time.monotonic();self.assertFalse(self.life.before_close())
            self.assertLess(time.monotonic()-start,.25)
            self.finish()

    def test_close_cancels_running_check_without_new_import(self):
        f=self.fixture
        entered=threading.Event()
        def collect(*a,**kw):
            entered.set();self.assertTrue(f.api.web_sync.cancel.wait(5))
            return {'collected_at':'2026-11-03T00:00:00Z','records':[], 'failure_reasons':[{'reason':'Stopped at safe request boundary'}],'actual_record_count':0,'request_count':1}
        with patch('web_sync.collect_game',side_effect=collect):
            self.assertEqual(f.request('/api/sync',{'action':'check','game':8552,'max_pages':1})[0],200)
            self.assertTrue(entered.wait(2));self.life.before_close();self.finish()
        with closing(sqlite3.connect(f.db)) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM mods').fetchone()[0],0)

    def test_pending_preview_is_preserved(self):
        f=self.fixture
        f.api.web_sync.state={'status':'waiting','token':'keep'};f.api.web_sync.save()
        original=f.api.web_sync.path.read_bytes()
        self.life.before_close();self.finish()
        self.assertEqual(f.api.web_sync.path.read_bytes(),original)

    def test_close_waits_for_transaction_and_preserves_personal_state(self):
        f=self.fixture;f.seed()
        f.request('/api/read-state',{'source':'gamebanana','item_id':1,'is_read':True})
        f.request('/api/subscription',{'source':'gamebanana','author_id':7,'followed':True})
        config=f.api.auto_sync.configure({'mode':'off','interval_hours':3,'max_pages':3})
        settings=f.api.auto_sync.directory/'settings.json';before=settings.read_bytes()
        entered=threading.Event();release=threading.Event()
        def transaction():
            with f.server.lifecycle_lock, closing(sqlite3.connect(f.db)) as c:
                c.execute('BEGIN IMMEDIATE');c.execute("UPDATE mods SET title='Committed safely' WHERE item_id=1")
                entered.set();release.wait(5);c.commit()
        worker=threading.Thread(target=transaction);worker.start();self.assertTrue(entered.wait(2))
        self.life.before_close();time.sleep(.1);self.assertFalse(self.destroyed.is_set())
        self.assertEqual(f.request('/api/read-state',{'source':'gamebanana','item_id':1,'is_read':False})[0],503)
        release.set();worker.join(5);self.finish()
        with closing(sqlite3.connect(f.db)) as c:
            self.assertEqual(c.execute('SELECT title FROM mods WHERE item_id=1').fetchone()[0],'Committed safely')
            self.assertEqual(c.execute('SELECT is_read FROM user_states').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM author_subscriptions').fetchone()[0],1)
        self.assertEqual(settings.read_bytes(),before)

    def test_timeout_leaves_live_transaction_and_window_intact(self):
        f=self.fixture;self.life.wait_seconds=.1
        f.api.auto_sync.running.acquire()
        try:
            self.life.before_close();self.life.worker.join(2)
            self.assertFalse(self.destroyed.is_set());self.assertFalse(f.closing.is_set())
            self.assertTrue(f.api.auto_sync.running.locked())
        finally:f.api.auto_sync.running.release()
        self.life.before_close();self.finish()

    def test_auto_worker_is_cancelled_and_joined(self):
        f=self.fixture;entered=threading.Event()
        f.api.auto_sync.configure({'mode':'check','interval_hours':3,'max_pages':1})
        def run(**kw):entered.set();self.assertTrue(f.api.auto_sync.cancel.wait(4))
        with patch.object(f.api.auto_sync,'run',side_effect=run):
            f.api.auto_sync.launch();self.assertTrue(entered.wait(2));self.life.before_close();self.finish()

    def test_history_worker_is_cancelled_without_persistent_pause(self):
        f=self.fixture;h=f.api.history_sync;entered=threading.Event()
        h.configure({'enabled':True,'paused':False,'max_pages':2});before=(h.directory/'settings.json').read_bytes()
        def run(**kw):entered.set();self.assertTrue(h.cancel.wait(4))
        with patch.object(h,'run',side_effect=run):
            h.launch(manual=True);self.assertTrue(entered.wait(2));self.life.before_close();self.finish()
        self.assertEqual((h.directory/'settings.json').read_bytes(),before)

    def test_rate_limit_or_network_failure_does_not_block_close(self):
        f=self.fixture
        f.api.web_sync.state={'status':'failed','scan_status':'rate_limited','failures':[{'http_status':429,'retry_after_seconds':3600},{'reason':'ReadTimeout'}]}
        f.api.web_sync.save();before=f.api.web_sync.path.read_bytes()
        self.life.before_close();self.finish();self.assertEqual(f.api.web_sync.path.read_bytes(),before)

    def test_repeated_close_uses_one_coordinator(self):
        f=self.fixture;f.api.web_sync.worker_active=True
        self.life.before_close();worker=self.life.worker
        self.assertFalse(self.life.before_close());self.assertIs(self.life.worker,worker)
        f.api.web_sync.worker_active=False;self.finish()

    def test_non_daemon_smoke_wait_is_cancelled_and_drained(self):
        ended=threading.Event()
        def smoke():
            self.fixture.closing.wait(60)
            ended.set()
        worker=threading.Thread(target=smoke,name='test-smoke',daemon=False)
        self.life.smoke_worker=worker;worker.start()
        self.life.before_close();self.finish()
        self.assertTrue(ended.is_set());self.assertFalse(worker.is_alive())

    def test_auto_apply_complete_then_close_preserves_settings(self):
        f=self.fixture
        f.api.auto_sync.configure({'mode':'apply','interval_hours':3,'max_pages':1})
        def collect(client,game,**kw):
            return {'collected_at':'2026-11-03T00:00:00Z','records':[{'source':'gamebanana','item_type':'Mod','item_id':game['game_id'],'game_id':game['game_id'],'title':'Fixture','created_at':'2026-11-02T00:00:00Z'}], 'failure_reasons':[],'actual_record_count':1,'request_count':1}
        with patch('web_sync.collect_game',side_effect=collect):
            f.api.auto_sync.launch();f.api.auto_sync.worker.join(15)
            self.assertFalse(f.api.auto_sync.worker.is_alive());self.assertFalse(f.api.auto_sync.running.locked())
        with closing(sqlite3.connect(f.db)) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM mods').fetchone()[0],6)
        self.life.before_close();self.finish()
        self.assertEqual(f.api.auto_sync.settings()['mode'],'apply')
