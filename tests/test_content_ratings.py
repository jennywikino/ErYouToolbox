import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from eryoutoolbox.database import initialize_database, connect_database, backup_database
from eryoutoolbox.content_ratings import source_ratings, save_verified_samples
from eryoutoolbox.importer import import_samples
from react_api import ReadOnlyAPI
from tests.test_backfill_previews import mod


class RatingPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.path = Path(self.temp.name) / 'test.db'
        initialize_database(self.path)
        self.c = connect_database(self.path)
        self.c.execute("INSERT INTO mods(source,item_type,item_id,game_id,preview_urls_json,content_rating_status,raw_metadata_json,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',42,8552,'[\"https://example.com/full.jpg\"]','ADULT',?, '2026-01-01','2026-01-01')", (json.dumps({'_record': {'note': 'keep'}, '_snapshot_collected_at': '2026-01-01T00:00:00Z', 'manual_review': 'keep'}),))
        self.c.execute("INSERT INTO user_states(source,item_type,item_id,note,updated_at) VALUES('gamebanana','Mod',42,'private note','2026-01-01')")
        self.c.commit()
        self.report = {'format': 'eryoutoolbox-rating-audit-v1', 'observed_at': '2026-10-29T00:00:00Z', 'samples': [
            {'source': 'gamebanana', 'item_type': 'Mod', 'item_id': 42, 'http_status': 200,
             'detail': {'_aContentRatings': {'pn': 'Partial Nudity', 'nu': 'Full Nudity', 'sc': 'Sexual Content'}}}]}

    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def backup(self):
        backup_database(self.path, Path(self.temp.name) / 'backup.db')

    def test_verified_labels_save_and_filter_without_changing_other_data(self):
        before = tuple(self.c.execute('SELECT preview_urls_json,content_rating_status,first_seen_at,last_checked_at FROM mods').fetchone())
        result = save_verified_samples(self.c, self.report, dry_run=False, before_write=self.backup)
        self.assertEqual(result['updated'], 1)
        self.assertEqual(tuple(self.c.execute('SELECT preview_urls_json,content_rating_status,first_seen_at,last_checked_at FROM mods').fetchone()), before)
        self.assertEqual(self.c.execute('SELECT note FROM user_states').fetchone()[0], 'private note')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM mod_events').fetchone()[0], 0)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM sync_runs').fetchone()[0], 0)
        raw = json.loads(self.c.execute('SELECT raw_metadata_json FROM mods').fetchone()[0])
        self.assertEqual(raw['manual_review'], 'keep')
        api = ReadOnlyAPI(self.path)
        for code in ('pn', 'nu', 'sc', 'pn,nu,sc'):
            self.assertEqual(api.get('/api/mods?ratings=' + code)[1]['total_count'], 1)
        self.assertEqual(api.get('/api/mods?ratings=UNKNOWN')[1]['total_count'], 0)
        second = save_verified_samples(self.c, self.report, dry_run=False,
                                       before_write=lambda: self.fail('Idempotent import must not back up'))
        self.assertEqual(second['updated'], 0)

    def test_dry_run_has_no_writes_or_backup(self):
        before = self.path.read_bytes()
        result = save_verified_samples(self.c, self.report, before_write=lambda: self.fail('dry-run backup'))
        self.assertEqual(result['candidates'], 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_backup_failure_rolls_back(self):
        before = self.c.execute('SELECT raw_metadata_json FROM mods').fetchone()[0]
        def fail():
            raise OSError('backup failure')
        with self.assertRaises(OSError):
            save_verified_samples(self.c, self.report, dry_run=False, before_write=fail)
        self.assertFalse(self.c.in_transaction)
        self.assertEqual(self.c.execute('SELECT raw_metadata_json FROM mods').fetchone()[0], before)

    def test_unknown_or_wrong_identity_cannot_write(self):
        self.report['samples'][0]['detail'] = {'_sInitialVisibility': 'hide'}
        self.assertEqual(save_verified_samples(self.c, self.report)['candidates'], 0)
        self.report['samples'][0]['detail'] = {'_aContentRatings': {'pn': 'Partial Nudity'}}
        self.report['samples'][0]['source'] = 'other'
        self.assertEqual(save_verified_samples(self.c, self.report)['candidates'], 0)

    def test_future_metadata_refresh_preserves_detail_evidence(self):
        save_verified_samples(self.c, self.report, dry_run=False, before_write=self.backup)
        sample = mod(item_id=42, title='New title')
        import_samples(self.c, [({'captured_at': datetime(2026, 10, 30, tzinfo=timezone.utc)}, [sample])], dry_run=False)
        raw = self.c.execute('SELECT raw_metadata_json FROM mods').fetchone()[0]
        self.assertEqual(source_ratings(raw)['codes'], ['pn', 'nu', 'sc'])

if __name__ == '__main__':
    unittest.main()
