from pathlib import Path
import sys
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'src')]
from backfill_content_ratings import FORMAT, inventory, run, fetch_batch, read_checkpoint
from eryoutoolbox.content_ratings import source_ratings
from eryoutoolbox.database import initialize_database, connect_database, backup_database


def response(item_id, fields=None, status=200, headers=None):
    return httpx.Response(status, json={'_idRow': item_id, **(fields or {})}, headers=headers,
                          request=httpx.Request('GET', 'https://gamebanana.com/test'))


class RatingBackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.directory = Path(self.temp.name)
        self.database = self.directory / 'test.db'
        self.checkpoint = self.directory / 'checkpoint.json'
        initialize_database(self.database)
        self.c = connect_database(self.database)
        for item_id in (1, 2, 3):
            self.c.execute("INSERT INTO mods(source,item_type,item_id,game_id,preview_urls_json,raw_metadata_json,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',?,8552,'[\"https://example.com/original.jpg\"]','{}','2026-01-01','2026-01-01')", (item_id,))
        self.c.execute("INSERT INTO user_states(source,item_type,item_id,note,updated_at) VALUES('gamebanana','Mod',1,'keep','2026-01-01')")
        self.c.commit()
        self.client = Mock()
        self.client.get.side_effect = lambda url: response(int(url.split('/')[-2]), {'_aContentRatings': {'pn': 'Partial Nudity'}})

    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def backup(self):
        backup_database(self.database, self.directory / 'backup.db')

    def execute(self, **kwargs):
        with patch('backfill_content_ratings.time.sleep'):
            return run(self.database, self.checkpoint, client=self.client, backup=self.backup, **kwargs)

    def test_inventory_and_verified_labels_are_never_requested_again(self):
        self.execute(apply=True, limit=1)
        self.assertEqual(inventory(self.database)['missing'], 2)
        self.client.reset_mock()
        result = self.execute(apply=True, limit=1, resume=True)
        self.assertEqual(result['selected_ids'], [2])
        self.assertEqual(self.client.get.call_count, 1)

    def test_dry_run_no_checkpoint_or_database_or_backup(self):
        before = self.database.read_bytes()
        result = self.execute(limit=2)
        self.assertEqual(result['requests'], 2)
        self.assertEqual(result['save']['candidates'], 2)
        self.assertFalse(self.checkpoint.exists())
        self.assertFalse((self.directory / 'backup.db').exists())
        self.assertEqual(self.database.read_bytes(), before)

    def test_dry_run_resume_preserves_checkpoint_bytes(self):
        self.execute(apply=True, limit=1)
        before = self.checkpoint.read_bytes()
        self.execute(resume=True, limit=1)
        self.assertEqual(self.checkpoint.read_bytes(), before)

    def test_apply_then_resume_preserves_images_states_and_counts(self):
        before = [tuple(row) for row in self.c.execute('SELECT item_id,preview_urls_json,first_seen_at,last_checked_at FROM mods')]
        self.execute(apply=True, limit=1)
        result = self.execute(apply=True, resume=True, limit=2)
        self.assertEqual(result['save']['updated'], 2)
        self.assertEqual(inventory(self.database)['total'], 3)
        self.assertEqual(before, [tuple(row) for row in self.c.execute('SELECT item_id,preview_urls_json,first_seen_at,last_checked_at FROM mods')])
        self.assertEqual(self.c.execute('SELECT note FROM user_states').fetchone()[0], 'keep')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM mod_events').fetchone()[0], 0)

    def test_backup_failure_does_not_advance_checkpoint(self):
        self.execute(apply=True, limit=1)
        before = self.checkpoint.read_bytes()
        with patch.object(self, 'backup', side_effect=OSError('backup failed')):
            result = self.execute(apply=True, resume=True, limit=1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.checkpoint.read_bytes(), before)
        self.assertEqual(inventory(self.database)['missing'], 2)

    def test_write_failure_rolls_back_and_does_not_create_checkpoint(self):
        self.c.execute("CREATE TRIGGER fail BEFORE UPDATE ON mods BEGIN SELECT RAISE(ABORT,'write failure'); END")
        self.c.commit()
        result = self.execute(apply=True, limit=2)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(self.checkpoint.exists())
        self.assertEqual(inventory(self.database)['missing'], 3)

    def test_failed_unknown_has_separate_explicit_retry_queue(self):
        self.client.get.side_effect = [response(3, {'_aContentRatings': {'pn': 'Partial Nudity'}}), response(2)]
        result = self.execute(apply=True, limit=2)
        self.assertEqual(result['retry_ids'], [2])
        self.assertEqual(inventory(self.database)['codes']['UNKNOWN'], 2)
        self.client.get.side_effect = lambda url: response(int(url.split('/')[-2]), {'_aContentRatings': {'sc': 'Sexual Content'}})
        result = self.execute(apply=True, resume=True, retry_failed=True, limit=1)
        self.assertEqual(result['selected_ids'], [2])
        self.assertEqual(result['retry_ids'], [])

    def test_explicit_unrated_flag_is_saved_with_timestamp(self):
        self.client.get.side_effect = lambda url: response(int(url.split('/')[-2]), {'_bHasContentRatings': False})
        self.execute(apply=True, limit=1)
        raw = self.c.execute('SELECT raw_metadata_json FROM mods WHERE item_id=3').fetchone()[0]
        rating = source_ratings(raw)
        self.assertEqual(rating['codes'], ['-'])
        self.assertTrue(rating['observed_at'])
        self.assertEqual(self.execute(apply=True, resume=True, limit=1)['selected_ids'], [2])

    def test_403_and_429_stop_without_further_requests(self):
        for status in (403, 429):
            with self.subTest(status=status):
                self.client.reset_mock()
                self.client.get.side_effect = None
                self.client.get.return_value = response(3, status=status, headers={'Retry-After': '60'})
                result = self.execute(limit=3)
                self.assertEqual(result['requests'], 1)
                self.assertEqual(result['failures']['3']['http_status'], status)
                self.assertEqual(result['failures']['3']['retry_after_seconds'], 60)

    def test_retry_after_deadline_prevents_immediate_resume(self):
        self.client.get.side_effect = [response(3, {'_aContentRatings': {'pn': 'Partial Nudity'}}),
                                       response(2, status=429, headers={'Retry-After': '60'})]
        self.execute(apply=True, limit=3)
        with self.assertRaisesRegex(ValueError, 'Retry-After active'):
            self.execute(resume=True)

    def test_total_source_failure_does_not_commit_checkpoint(self):
        self.client.get.side_effect = None
        self.client.get.return_value = response(3, status=403)
        result = self.execute(apply=True, limit=3)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(self.checkpoint.exists())

    def test_network_and_invalid_response_stop_and_remain_unknown(self):
        for value in (httpx.ConnectError('offline'), response(99)):
            self.client.reset_mock()
            self.client.get.side_effect = value if isinstance(value, Exception) else None
            self.client.get.return_value = value
            result = self.execute(limit=3)
            self.assertEqual(result['requests'], 1)
            self.assertTrue(result['failures'])
            self.assertEqual(inventory(self.database)['missing'], 3)

    def test_limits_and_checkpoint_identity(self):
        with self.assertRaises(ValueError):
            self.execute(limit=21)
        self.assertEqual(self.client.get.call_count, 0)
        self.checkpoint.write_text(json.dumps({'format': FORMAT, 'game': 19567, 'attempted_ids': [], 'failures': {}}))
        with self.assertRaisesRegex(ValueError, 'wrong game'):
            read_checkpoint(self.checkpoint, 8552)


if __name__ == '__main__':
    unittest.main()
