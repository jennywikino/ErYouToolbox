"""Browser orchestration uses temporary SQLite and simulated bounded source pages."""
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch

import test_auto_sync as fixtures
from auto_sync import AutoSync, DEFAULTS
from backfill_content_ratings import instance_lock
from eryoutoolbox.database import connect_database
from web_sync import WebSync


class BrowserSyncTests(unittest.TestCase):
    def setUp(self):
        fixtures.AutomaticSyncTests.setUp(self)
        # Author rotation is not under test here; never contact a real author.
        rotation=patch('eryoutoolbox.author_updates.run_rotation',return_value={
            'status':'success','requests':0,'followed_count':0,'checked_authors':0,'pending_count':0})
        rotation.start();self.addCleanup(rotation.stop)
        delay=patch('web_sync.time.sleep')
        delay.start();self.addCleanup(delay.stop)

    tearDown = fixtures.AutomaticSyncTests.tearDown
    source = fixtures.AutomaticSyncTests.source
    count = fixtures.AutomaticSyncTests.count

    def finish(self):
        self.auto.worker.join(15)
        self.assertFalse(self.auto.worker.is_alive())

    def browser(self, startup=True, **kwargs):
        result = self.auto.browser_launch(startup=startup, **kwargs)
        if result['status'] == 'requested':self.finish()
        return result

    def test_fresh_empty_six_games_bounded_automatic_import_and_restart(self):
        self.auto.games = [{'game_id': gid, 'name': str(gid)} for gid in (8552, 18366, 19567, 20357, 21842, 23012)]
        with patch('web_sync.collect_game', side_effect=self.source) as request:
            self.assertEqual(self.browser()['status'], 'requested')
            self.assertEqual([c.args[1]['game_id'] for c in request.call_args_list], [g['game_id'] for g in self.auto.games])
            self.assertEqual(request.call_count, 6)
        self.assertEqual(self.count('mods'), 6)
        self.assertEqual(self.auto.settings(), DEFAULTS)  # Existing task settings are not rewritten.
        self.assertTrue(self.auto.status()['last_run']['initial_sync'])
        self.assertEqual(self.auto.status()['last_run']['inserted'], 6)
        self.assertIsNone(WebSync(self.db, self.root, self.auto.games).candidate)
        self.assertEqual(len(list((self.db.parent/'backups').glob('*.db'))), 1)
        fresh = AutoSync(self.root, self.db, self.auto.games, self.root/'device')
        with patch('web_sync.collect_game',side_effect=self.source) as request:
            fresh.browser_launch(startup=True);fresh.worker.join(15)
            self.assertFalse(fresh.worker.is_alive());self.assertEqual(request.call_count,18)
        self.assertEqual(self.count('mods'), 6)

    def test_browser_startup_import_is_independent_of_legacy_task_mode(self):
        for mode in ['off','check']:
            self.auto=AutoSync(self.root,self.db,self.games,self.root/'device')
            self.auto.configure({**DEFAULTS,'mode':mode})
            with patch('web_sync.collect_game',side_effect=self.source):self.browser()
            self.assertEqual(self.count('mods'),2)
            self.assertEqual(self.auto.settings()['mode'],mode)
            self.assertEqual(self.auto.status()['last_run']['status'],'success')

    def test_manual_refresh_imports_even_when_saved_mode_off(self):
        self.auto.configure({**DEFAULTS, 'mode': 'off', 'max_pages': 1})
        with patch('web_sync.collect_game', side_effect=self.source):self.browser(startup=False, game=8552)
        self.assertEqual(self.count('mods'), 1)
        self.assertEqual(self.auto.settings()['mode'], 'off')
        with patch('web_sync.collect_game') as request:
            self.browser(startup=False, game=8552);request.assert_not_called()

    def test_existing_database_once_per_service_restart_idempotent(self):
        self.auto.configure({**DEFAULTS, 'mode': 'apply', 'max_pages': 1})
        with patch('web_sync.collect_game', side_effect=self.source), patch('auto_sync.time.time', return_value=2_000_000_000):self.browser()
        with patch('web_sync.collect_game') as request:
            self.assertEqual(self.browser()['status'],'startup_already_requested');request.assert_not_called()
        self.auto=AutoSync(self.root,self.db,self.games,self.root/'device')
        with patch('web_sync.collect_game', side_effect=self.source) as request, patch('auto_sync.time.time', return_value=2_000_000_001):
            self.browser()  # Restart does not wait for the previous hourly interval.
            self.assertEqual(request.call_count, 2)
        self.assertFalse(self.auto.status()['last_run']['initial_sync'])
        self.assertEqual(self.count('mods'), 2)
        self.assertEqual(self.count('mod_events'), 2)
        self.assertEqual(self.auto.status()['last_run']['inserted'], 0)

    def test_offline_keeps_existing_database_and_user_state(self):
        self.auto.configure({**DEFAULTS, 'mode': 'apply', 'max_pages': 1})
        with patch('web_sync.collect_game', side_effect=self.source):self.browser()
        c=connect_database(self.db)
        c.execute("UPDATE user_states SET is_read=1,note='retain',is_favorite=1")
        c.execute("INSERT INTO author_subscriptions VALUES('gamebanana',7,'Author','2026-01-01T00:00:00Z')")
        c.commit();before=[tuple(r) for r in c.execute('SELECT * FROM user_states')];c.close()
        def offline(client,game,**kwargs):
            value=self.source(client,game,**kwargs)
            return {**value,'records':[],'actual_record_count':0,'failure_reasons':[{'reason':'ReadTimeout','http_status':None}]}
        with patch('web_sync.collect_game',side_effect=offline),patch('auto_sync.time.time',return_value=2_000_000_000):self.browser(startup=False)
        c=connect_database(self.db)
        try:
            self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM user_states')])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM author_subscriptions').fetchone()[0],1)
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:c.close()
        self.assertEqual(self.count('mods'),2)
        self.assertEqual(self.auto.status()['last_run']['status'],'failed')

    def test_partial_game_failure_imports_only_validated_results(self):
        def partial(client, game, **kwargs):
            value=self.source(client,game,**kwargs)
            return {**value,'records':[],'actual_record_count':0,'failure_reasons':[{'reason':'ReadTimeout'}]} if game['game_id']==8552 else value
        with patch('web_sync.collect_game',side_effect=partial):self.browser()
        self.assertEqual(self.count('mods'),1)
        self.assertEqual(self.auto.status()['last_run']['status'],'partial')
        self.assertEqual(self.auto.status()['last_run']['inserted'],1)

    def test_failed_startup_is_once_but_manual_retry_can_recover(self):
        def offline(*args,**kwargs):
            value=self.source(*args,**kwargs)
            return {**value,'records':[],'actual_record_count':0,'failure_reasons':[{'reason':'offline'}]}
        with patch('web_sync.collect_game',side_effect=offline) as request:
            self.browser()
            self.assertEqual(self.auto.status()['last_run']['status'],'failed')
            self.assertEqual(self.browser()['status'],'startup_already_requested')
            self.assertEqual(request.call_count,2)
        with patch('web_sync.collect_game',side_effect=self.source),patch('auto_sync.time.time',return_value=2_000_000_000):
            self.browser(startup=False)
        self.assertEqual(self.count('mods'),2)
        self.assertEqual(self.auto.status()['last_run']['status'],'success')

    def test_duplicate_refresh_running_and_shared_lock(self):
        entered,release=threading.Event(),threading.Event()
        def source(*args,**kwargs):
            entered.set();self.assertTrue(release.wait(10));return self.source(*args,**kwargs)
        with patch('web_sync.collect_game',side_effect=source) as request:
            try:
                self.auto.browser_launch(startup=True);self.assertTrue(entered.wait(10))
                self.assertEqual(self.auto.browser_launch(startup=True)['status'],'startup_already_requested')
                self.assertEqual(self.auto.browser_launch()['status'],'already_running')
            finally:release.set();self.finish()
            self.assertEqual(request.call_count,2)
        with instance_lock(self.root/'logs/content_ratings/instance.lock'),patch('web_sync.collect_game') as request:
            self.browser(startup=False);request.assert_not_called()

    def test_pending_manual_lookup_is_not_overwritten(self):
        service=WebSync(self.db,self.root,self.games)
        with patch('web_sync.collect_game',side_effect=self.source):service.check_games(self.games,max_pages=1)
        before=service.path.read_bytes()
        with patch('web_sync.collect_game') as request:self.browser();request.assert_not_called()
        self.assertEqual(service.path.read_bytes(),before)
        self.assertEqual(self.auto.status()['last_run']['status'],'manual_preview_pending')
        self.assertEqual(self.count('mods'),0)

    def test_backup_failure_rollback_and_invalid_game(self):
        with patch('web_sync.collect_game',side_effect=self.source),patch('web_sync.backup_database',side_effect=OSError('backup unavailable')):self.browser()
        self.assertEqual(self.count('mods'),0)
        self.assertEqual(self.count('sync_runs'),0)
        self.assertEqual(self.auto.status()['last_run']['status'],'failed')
        with self.assertRaises(ValueError):self.auto.browser_launch(game=True)

    def test_refresh_stopped_during_check_does_not_write(self):
        self.auto.configure({**DEFAULTS,'mode':'off','max_pages':1})
        def stopped(*args,**kwargs):
            self.auto.stop()
            return self.source(*args,**kwargs)
        with patch('web_sync.collect_game',side_effect=stopped):self.browser(startup=False)
        self.assertEqual(self.count('mods'),0)
        self.assertEqual(self.count('sync_runs'),0)
        self.assertEqual(self.auto.status()['last_run']['status'],'failed')

    def test_refresh_cannot_bypass_429_cooldown(self):
        def limited(*args,**kwargs):
            value=self.source(*args,**kwargs)
            return {**value,'records':[],'actual_record_count':0,
                    'failure_reasons':[{'http_status':429,'reason':'Retry-After','retry_after_seconds':20000}]}
        with patch('web_sync.collect_game',side_effect=limited) as request:
            self.browser();self.browser(startup=False)
            self.assertEqual(request.call_count,1)
        self.assertGreater(self.auto.status()['last_run']['not_before'],0)
        self.assertEqual(self.count('mods'),0)

    def test_http_refresh_origin_and_browser_restart(self):
        from react_api import ReadOnlyAPI,make_handler
        api=ReadOnlyAPI(self.db,runtime_root=self.root)
        api.auto_sync=self.auto
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(api,0))
        server.RequestHandlerClass=make_handler(api,server.server_port)
        worker=threading.Thread(target=server.serve_forever);worker.start()
        connection=HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        try:
            with patch('web_sync.collect_game',side_effect=self.source):
                for origin,expected in [('https://example.com',403),(f'http://127.0.0.1:{server.server_port}',200)]:
                    connection.request('POST','/api/auto-sync/refresh',json.dumps({'game':8552}),
                        {'Origin':origin,'Content-Type':'application/json','X-ErYouToolbox':'1'})
                    response=connection.getresponse();response.read();self.assertEqual(response.status,expected)
                connection.close();self.finish()
            status,result=api.get('/api/mods?game=8552')
            self.assertEqual(status,200);self.assertEqual(result['total_count'],1)
            fresh=AutoSync(self.root,self.db,self.games,self.root/'device')
            self.assertEqual(fresh.status()['last_run']['inserted'],1)
        finally:
            connection.close();server.shutdown();server.server_close();worker.join(5)


if __name__=='__main__':unittest.main()
