import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).resolve().parents[1]/'src')]
import test_auto_sync as fixtures
from eryoutoolbox.database import connect_database
from eryoutoolbox.importer import import_samples,parse_utc
from web_sync import automatic_candidates


class SyncPerformanceTests(unittest.TestCase):
    setUp=fixtures.AutomaticSyncTests.setUp
    tearDown=fixtures.AutomaticSyncTests.tearDown
    source=fixtures.AutomaticSyncTests.source
    run_auto=fixtures.AutomaticSyncTests.run_auto
    configure=fixtures.AutomaticSyncTests.configure
    count=fixtures.AutomaticSyncTests.count
    def test_same_timestamp_skips_comparison_new_update_is_kept(self):
        self.configure('apply');self.run_auto()
        c=connect_database(self.db)
        try:
            result=self.source(None,self.games[0])
            meta={'captured_at':parse_utc('2026-11-01T00:00:00Z')}
            with patch('web_sync.import_samples',wraps=import_samples) as compare:
                selected=automatic_candidates(c,[(meta,result['records'])])
                self.assertEqual(selected[0][1],[]);compare.assert_not_called()
            result['records'][0]['updated_at']='2026-10-31T00:00:00Z'
            with patch('web_sync.import_samples',wraps=import_samples) as compare:
                selected=automatic_candidates(c,[(meta,result['records'])])
                self.assertEqual(len(selected[0][1]),1);self.assertEqual(compare.call_count,1)
        finally:c.close()
    def test_missing_evidence_uses_existing_importer(self):
        self.configure('apply');self.run_auto();record=self.source(None,self.games[0])['records'][0]
        record['updated_at']=None
        c=connect_database(self.db)
        try:
            with patch('web_sync.import_samples',wraps=import_samples) as compare:
                automatic_candidates(c,[({'captured_at':parse_utc('2026-11-01T00:00:00Z')},[record])])
                self.assertEqual(compare.call_count,1)
        finally:c.close()
    def test_metrics_and_no_unchanged_mod_writes(self):
        self.configure('apply');self.run_auto();c=connect_database(self.db)
        c.execute("CREATE TRIGGER reject_mod BEFORE UPDATE ON mods BEGIN SELECT RAISE(ABORT,'unchanged MOD write'); END")
        c.commit();c.close()
        record=self.run_auto()
        self.assertEqual(record['status'],'success');self.assertEqual(record['unchanged'],2)
        self.assertEqual(record['performance']['additional_detail_requests'],0)
        self.assertGreaterEqual(record['performance']['batch_import_seconds'],0)
        for game in record['games']:
            self.assertEqual(game['requests'],1);self.assertEqual(game['timestamp_skipped'],1)
            self.assertGreaterEqual(game['network_seconds'],0);self.assertGreaterEqual(game['selection_seconds'],0)
            self.assertEqual(game['batch_import_seconds_shared'],record['performance']['batch_import_seconds'])
    def test_author_failure_not_shown_as_zero_failures(self):
        self.configure('apply')
        with patch('eryoutoolbox.author_updates.run_rotation',return_value={'status':'partial','requests':0,'pending_count':1}):
            record=self.run_auto()
        self.assertEqual(record['status'],'partial');self.assertEqual(len(record['failures']),0)
        self.assertEqual(record['failure_count'],1);self.assertEqual(record['author_failures'],1)


if __name__=='__main__':unittest.main()
