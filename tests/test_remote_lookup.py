import unittest
from unittest.mock import patch
import test_web_sync as fixtures
from eryoutoolbox.ui_queries import query_mods
from web_sync import recent_window


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WebSyncTests('test_preview_and_restart_persistence');self.f.setUp()
        self.s=self.f.service;self.g=self.f.game
        self.record={'source':'gamebanana','item_type':'Mod','item_id':541855,'game_id':8552,'title':'Old title','category':'Skins','created_at':'2024-09-13T09:36:42Z','modified_at':'2026-10-26T14:23:33Z'}
    def tearDown(self):self.f.tearDown()
    def lookup(self):
        with patch('eryoutoolbox.source_detail.SourceDetail.fetch',return_value=self.record):self.s.lookup(self.g,541855)
    def test_modified_discovery_not_source_update(self):
        self.assertEqual(recent_window(self.record,'2026-11-03T00:00:00Z'),'in_window')
        self.lookup();self.assertEqual(self.f.count('mods'),0);self.s.apply()
        self.assertEqual(self.s.state['report']['source_update_events'],0)
        self.assertEqual(self.s.committed(),{})
        self.assertEqual(query_mods(self.f.db,search='541855')['total_count'],1)
        self.assertEqual(query_mods(self.f.db,search='541855',category='UI')['total_count'],0)
        with self.assertRaisesRegex(ValueError,'already stored'):self.lookup()
        self.assertEqual(self.f.count('mods'),1)
    def test_old_release_new_update_and_old_all_dates(self):
        self.assertEqual(recent_window({**self.record,'modified_at':None,'updated_at':'2026-10-26T00:00:00Z'},'2026-11-03T00:00:00Z'),'in_window')
        self.assertEqual(recent_window({**self.record,'modified_at':None},'2026-11-03T00:00:00Z'),'out_of_window')
        self.assertEqual(recent_window({},'2026-11-03T00:00:00Z'),'missing_dates')
    def test_lookup_does_not_claim_pagination_coverage(self):
        self.lookup();self.assertEqual(self.s.state['coverage'],'incomplete');self.assertEqual(self.s.state['games'],[])
        self.assertEqual(self.s.committed(),{})
    def test_identity_failure(self):
        self.record['game_id']=20357
        with self.assertRaisesRegex(ValueError,'identity'):self.lookup()
        self.assertEqual(self.f.count('mods'),0)
    def test_failure_and_rate_limit_no_write(self):
        for error in [RuntimeError('HTTP 429; Retry-After=60'),RuntimeError('HTTP 404'),TimeoutError('ReadTimeout')]:
            with patch('eryoutoolbox.source_detail.SourceDetail.fetch',side_effect=error):
                with self.assertRaises(type(error)):self.s.lookup(self.g,541855)
        self.assertIsNone(self.s.candidate);self.assertEqual(self.f.count('mods'),0)
    def test_backup_failure_retains_candidate_and_rolls_back(self):
        self.lookup()
        with patch('web_sync.backup_database',side_effect=OSError('backup failed')):
            with self.assertRaises(OSError):self.s.apply()
        self.assertEqual(self.f.count('mods'),0);self.assertIsNotNone(self.s.candidate)

    def test_worker_preview_confirm_and_metadata_change_not_update(self):
        with patch('eryoutoolbox.source_detail.SourceDetail.fetch',return_value=self.record):
            self.s.start({'action':'lookup','game':8552,'item_id':541855});self.s.worker.join(5)
        self.assertEqual(self.s.state['status'],'waiting')
        self.s.start({'action':'confirm','game':8552,'token':self.s.state['token']});self.s.worker.join(5)
        self.assertEqual(self.f.count('mods'),1);self.assertEqual(self.s.committed(),{})
        newer={**self.record,'modified_at':'2026-11-03T00:00:00Z'}
        self.f.check({'collected_at':'2026-11-04T00:00:00Z','records':[newer],'failure_reasons':[],'actual_record_count':1,'request_count':1})
        self.assertEqual(self.s.state['report']['source_update_events'],0)
