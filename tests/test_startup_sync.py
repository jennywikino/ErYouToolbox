"""Browser startup uses the existing worker; all databases/network are isolated."""
import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import test_auto_sync as fixtures
from auto_sync import AutoSync, DEFAULTS, atomic_json
from backfill_content_ratings import instance_lock
from react_api import ReadOnlyAPI, make_handler
from web_sync import WebSync


class StartupSyncTests(unittest.TestCase):
    setUp = fixtures.AutomaticSyncTests.setUp
    tearDown = fixtures.AutomaticSyncTests.tearDown
    count = fixtures.AutomaticSyncTests.count
    source = fixtures.AutomaticSyncTests.source

    def configure(self, mode):
        self.auto.configure({**DEFAULTS, 'mode':mode, 'max_pages':1})

    def finish(self):
        self.assertTrue(self.auto.running.acquire(timeout=15), 'Worker did not finish')
        self.auto.running.release()

    def startup(self):
        result = self.auto.launch(startup=True)
        self.finish()
        return result

    def test_due_then_refresh_and_interval_clock(self):
        self.configure('check')
        with patch('auto_sync.time.time', return_value=2_000_000_000), patch('web_sync.collect_game', side_effect=self.source) as request:
            self.startup()
            self.assertEqual(request.call_count, 2)
            self.startup()
            fresh = AutoSync(self.root, self.db, self.games, self.root/'device')
            self.assertEqual(fresh.run()['status'], 'not_due')
            self.assertEqual(request.call_count, 2)
            self.assertEqual(self.count('mods'), 0)
            self.assertEqual(self.count('sync_runs'), 0)
            self.assertFalse((self.db.parent/'backups').exists())
        # A saved check preview remains protected even after the interval.
        with patch('auto_sync.time.time', return_value=2_000_000_001+6*3600), patch('web_sync.collect_game') as request:
            # Its original ten-minute validity has expired, so a new scan is due.
            request.side_effect = self.source
            self.startup()
            self.assertEqual(request.call_count, 2)

    def test_off_no_network_or_report(self):
        with patch('web_sync.collect_game') as request:
            self.assertEqual(self.startup()['status'], 'disabled')
            request.assert_not_called()
        self.assertFalse((self.root/'device/last_run.json').exists())

    def test_apply_existing_rules_and_repeat(self):
        self.configure('apply')
        with patch('web_sync.collect_game', side_effect=self.source):
            self.startup()
            self.assertEqual(self.count('mods'), 2)
            self.startup()
            self.assertEqual(self.count('mods'), 2)
            self.assertEqual(self.count('mod_events'), 2)

    def test_tabs_and_existing_task_share_locks(self):
        self.configure('check')
        entered, release = threading.Event(), threading.Event()
        def source(*args, **kwargs):
            entered.set()
            if not release.wait(10): raise RuntimeError('Test worker timeout')
            return self.source(*args, **kwargs)
        with patch('web_sync.collect_game', side_effect=source) as request:
            try:
                self.auto.launch(startup=True)
                self.assertTrue(entered.wait(10))
                self.assertEqual(self.auto.launch(startup=True)['status'], 'already_running')
                other = AutoSync(self.root, self.db, self.games, self.root/'device')
                other.launch(startup=True)
                self.assertTrue(other.running.acquire(timeout=5)); other.running.release()
            finally:
                release.set(); self.finish()
            self.assertEqual(request.call_count, 2)
        with instance_lock(self.root/'logs/content_ratings/instance.lock'), patch('web_sync.collect_game') as request:
            self.startup(); request.assert_not_called()

    def test_cooldown_preserved(self):
        self.configure('check')
        atomic_json(self.root/'device/last_run.json', {'status':'failed','started_epoch':100,'not_before':9999})
        with patch('auto_sync.time.time', return_value=200), patch('web_sync.collect_game') as request:
            self.startup(); request.assert_not_called()
        self.assertEqual(json.loads((self.root/'device/last_run.json').read_text())['not_before'], 9999)

    def test_429_startup_stops_and_refresh_cannot_retry(self):
        self.configure('check')
        def limited(*args, **kwargs):
            result=self.source(*args, **kwargs)
            result.update(records=[], actual_record_count=0, failure_reasons=[{'http_status':429,'reason':'Retry-After respected by collector'}])
            return result
        with patch('auto_sync.time.time', return_value=2_000_000_000), patch('web_sync.collect_game', side_effect=limited) as request:
            self.startup(); self.startup()
            self.assertEqual(request.call_count, 1)
            self.assertGreater(self.auto.status()['last_run']['not_before'], 2_000_000_000)

    def test_startup_preserves_automatic_preview_too(self):
        service=WebSync(self.db,self.root,self.games)
        with patch('web_sync.collect_game',side_effect=self.source):service.check_games(self.games,max_pages=1)
        service.state['automatic']=True;service.save();before=service.path.read_bytes()
        self.configure('apply')
        with patch('web_sync.collect_game') as request:self.startup();request.assert_not_called()
        self.assertEqual(service.path.read_bytes(),before)
        self.assertEqual(self.count('mods'),0)

    def test_pending_preview_unchanged(self):
        service = WebSync(self.db, self.root, self.games)
        with patch('web_sync.collect_game', side_effect=self.source): service.check_games(self.games, max_pages=1)
        before = service.path.read_bytes()
        self.configure('apply')
        with patch('web_sync.collect_game') as request:
            self.startup(); request.assert_not_called()
        self.assertEqual(service.path.read_bytes(), before)
        self.assertEqual(self.count('mods'), 0)
        self.assertEqual(service.committed(), {})

    def test_network_failure_then_due_recovery(self):
        self.configure('check')
        def failed(*args, **kwargs):
            result = self.source(*args, **kwargs)
            result.update(records=[], actual_record_count=0, failure_reasons=[{'reason':'ReadTimeout'}])
            return result
        with patch('auto_sync.time.time', return_value=2_000_000_000), patch('web_sync.collect_game', side_effect=failed):
            self.startup()
            self.assertEqual(self.auto.status()['last_run']['status'], 'failed')
        with patch('auto_sync.time.time', return_value=2_000_000_001+6*3600), patch('web_sync.collect_game', side_effect=self.source):
            self.startup()
            self.assertEqual(self.auto.status()['last_run']['status'], 'waiting')

    def test_startup_http_origin_and_browser_disconnect(self):
        self.configure('check')
        api = ReadOnlyAPI(self.db); api.auto_sync = self.auto
        server = ThreadingHTTPServer(('127.0.0.1',0), make_handler(api,0))
        port = server.server_address[1]; server.RequestHandlerClass = make_handler(api,port)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with patch('web_sync.collect_game', side_effect=self.source):
                connection = HTTPConnection('127.0.0.1', port, timeout=10)
                connection.request('POST','/api/auto-sync/startup','{}', {'Origin':'https://other.example','Content-Type':'application/json','X-ErYouToolbox':'1'})
                response=connection.getresponse(); response.read(); self.assertEqual(response.status,403)
                connection.request('POST','/api/auto-sync/startup','{}', {'Origin':'http://127.0.0.1:5173','Content-Type':'application/json','X-ErYouToolbox':'1'})
                response=connection.getresponse(); response.read(); self.assertEqual(response.status,200)
                connection.close()  # No browser connection owns/cancels the worker.
                self.finish()
                self.assertEqual(self.auto.status()['last_run']['status'], 'success')
                self.assertEqual(self.count('mods'), 2)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__': unittest.main()
