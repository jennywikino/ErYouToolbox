import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'src')]
from run_rating_backfill import schedule
from backfill_content_ratings import FORMAT, instance_lock, inventory
from eryoutoolbox.database import initialize_database, connect_database, backup_database
from tests.test_rating_backfill import response


class RatingSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.directory = Path(self.temp.name)
        self.database = self.directory / 'test.db'
        self.checkpoint = self.directory / 'progress.json'
        self.lock = self.directory / 'instance.lock'
        initialize_database(self.database)
        self.c = connect_database(self.database)
        for item_id in range(1, 8):
            self.c.execute("INSERT INTO mods(source,item_type,item_id,game_id,preview_urls_json,raw_metadata_json,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',?,8552,'[\"https://example.com/full.jpg\"]','{}','2026-01-01','2026-01-01')", (item_id,))
        self.c.execute("INSERT INTO user_states(source,item_type,item_id,note,updated_at) VALUES('gamebanana','Mod',1,'preserve','2026-01-01')")
        self.c.commit()
        self.client = Mock()
        self.client.get.side_effect = lambda url: response(int(url.split('/')[-2]), {'_aContentRatings': {'pn': 'Partial Nudity'}})
        self.backups = []

    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def backup(self, number):
        path = self.directory / f'backup_{len(self.backups)}.db'
        backup_database(self.database, path)
        self.backups.append(path)
        return path

    def execute(self, **kwargs):
        with patch('backfill_content_ratings.time.sleep'), patch('run_rating_backfill.time.sleep'):
            return schedule(self.database, self.checkpoint, client=self.client, backup_factory=self.backup,
                            lock_path=self.lock, **kwargs)

    def test_default_dry_run_only_first_batch_and_no_writes(self):
        before = self.database.read_bytes()
        result = self.execute(limit=2)
        self.assertEqual(len(result['batches']), 1)
        self.assertEqual(result['totals']['requests'], 2)
        self.assertEqual(result['batches'][0]['save']['candidates'], 2)
        self.assertEqual(before, self.database.read_bytes())
        self.assertFalse(self.checkpoint.exists())
        self.assertEqual(self.backups, [])

    def test_three_batches_sequential_success_and_request_spacing(self):
        with patch('backfill_content_ratings.time.sleep') as sleep:
            result = schedule(self.database, self.checkpoint, client=self.client, backup_factory=self.backup,
                              lock_path=self.lock, apply=True, limit=2)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['totals']['updated'], 6)
        self.assertEqual(len(result['batches']), 3)
        self.assertEqual(len(self.backups), 3)
        self.assertTrue(all(call.args[0] >= 2 for call in sleep.call_args_list))
        self.assertEqual(inventory(self.database)['missing'], 1)
        self.assertEqual(self.c.execute('SELECT note FROM user_states').fetchone()[0], 'preserve')

    def test_maximum_batch_limit_and_no_unbounded_loop(self):
        result = self.execute(apply=True, batches=5, limit=1)
        self.assertEqual(len(result['batches']), 5)
        self.assertEqual(self.client.get.call_count, 5)
        with self.assertRaises(ValueError):
            self.execute(batches=6)
        with self.assertRaises(ValueError):
            self.execute(interval=1)

    def test_second_batch_failure_stops_and_checkpoint_stays_on_first(self):
        self.client.get.side_effect = [response(7, {'_aContentRatings': {'pn': 'Partial Nudity'}}), httpx.ReadTimeout('timeout')]
        result = self.execute(apply=True, limit=1)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['batches']), 2)
        checkpoint = json.loads(self.checkpoint.read_text())
        self.assertEqual(checkpoint['attempted_ids'], [7])
        error = result['errors'][0]
        self.assertEqual((error['mod_id'], error['error_type'], error['batch']), (6, 'ReadTimeout', 2))
        self.assertTrue(error['failed_at'])
        self.assertTrue(error['retryable'])

    def test_verified_records_skip_and_repeated_run_is_idempotent(self):
        self.execute(apply=True, limit=3)
        before = self.database.read_bytes()
        self.client.reset_mock()
        backup_count = len(self.backups)
        result = self.execute(apply=True, limit=3)
        self.assertEqual(result['totals']['updated'], 0)
        self.assertEqual(self.client.get.call_count, 0)
        self.assertEqual(len(self.backups), backup_count)
        self.assertEqual(before, self.database.read_bytes())

    def test_rate_limit_stops_all_batches_and_preserves_retry_after(self):
        self.client.get.side_effect = [response(7, {'_aContentRatings': {'pn': 'Partial Nudity'}}),
                                       response(6, status=429, headers={'Retry-After': '60'})]
        result = self.execute(apply=True, limit=2)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['batches']), 1)
        self.assertEqual(result['errors'][0]['retry_after'], '60')
        self.assertTrue(result['not_before'])
        self.client.reset_mock()
        again = self.execute(apply=True, limit=2)
        self.assertEqual(again['status'], 'failed')
        self.assertEqual(self.client.get.call_count, 0)

    def test_sqlite_failure_rolls_back_and_no_checkpoint(self):
        self.c.execute("CREATE TRIGGER fail BEFORE UPDATE ON mods BEGIN SELECT RAISE(ABORT,'write failed'); END")
        self.c.commit()
        result = self.execute(apply=True, limit=2)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(self.backups), 1)
        self.assertFalse(self.checkpoint.exists())
        self.assertEqual(inventory(self.database)['missing'], 7)
        self.assertEqual(result['errors'][0]['error_type'], 'IntegrityError')

    def test_all_failed_429_restart_respects_pause_without_advancing_checkpoint(self):
        self.client.get.side_effect = None
        self.client.get.return_value = response(7, status=429, headers={'Retry-After': '60'})
        first = self.execute(apply=True, limit=2)
        self.assertEqual(first['status'], 'failed')
        self.assertFalse(self.checkpoint.exists())
        self.assertTrue(first['not_before'])
        self.client.reset_mock()
        second = self.execute(apply=True, limit=2)
        self.assertEqual(second['status'], 'failed')
        self.assertEqual(self.client.get.call_count, 0)

    def test_backup_failure_no_database_changes(self):
        with patch.object(self, 'backup', side_effect=OSError('backup failed')):
            result = self.execute(apply=True, limit=2)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(self.checkpoint.exists())
        self.assertEqual(inventory(self.database)['missing'], 7)

    def test_ctrl_c_during_request_then_resume(self):
        self.client.get.side_effect = [response(7, {'_aContentRatings': {'pn': 'Partial Nudity'}}), KeyboardInterrupt()]
        result = self.execute(apply=True, limit=1)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(json.loads(self.checkpoint.read_text())['attempted_ids'], [7])
        self.client.get.side_effect = lambda url: response(int(url.split('/')[-2]), {'_aContentRatings': {'pn': 'Partial Nudity'}})
        resumed = self.execute(apply=True, limit=1, batches=1)
        self.assertEqual(resumed['batches'][0]['selected_ids'], [6])

    def test_ctrl_c_during_backup_stops_without_checkpoint(self):
        with patch.object(self, 'backup', side_effect=KeyboardInterrupt()):
            result = self.execute(apply=True, limit=2)
        self.assertEqual(result['status'], 'stopped')
        self.assertFalse(self.checkpoint.exists())
        self.assertEqual(inventory(self.database)['missing'], 7)

    def test_ctrl_c_after_first_update_rolls_back_entire_transaction(self):
        from eryoutoolbox.content_ratings import save_verified_samples
        actual = self.c
        class InterruptedConnection:
            def __getattr__(self, name):
                return getattr(actual, name)
            def executemany(self, sql, rows):
                actual.execute(sql, rows[0])
                raise KeyboardInterrupt()
        report = {'format': 'eryoutoolbox-rating-audit-v1', 'observed_at': '2026-10-29T00:00:00Z',
                  'samples': [{'source': 'gamebanana', 'item_type': 'Mod', 'item_id': i,
                               'http_status': 200, 'detail': {'_aContentRatings': {'pn': 'Partial Nudity'}}} for i in (7, 6)]}
        with self.assertRaises(KeyboardInterrupt):
            save_verified_samples(InterruptedConnection(), report, dry_run=False, before_write=lambda: self.backup(1))
        self.assertFalse(actual.in_transaction)
        self.assertEqual(inventory(self.database)['missing'], 7)
        self.assertFalse(self.checkpoint.exists())

    def test_existing_failure_queue_not_overwritten(self):
        self.checkpoint.write_text(json.dumps({'format': FORMAT, 'game': None,
            'attempted_ids': [1], 'failures': {'1': {'reason': 'old failure'}}}))
        result = self.execute(apply=True, limit=1, batches=1)
        self.assertEqual(result['pending_failures']['1']['reason'], 'old failure')
        self.assertEqual(json.loads(self.checkpoint.read_text())['failures']['1']['reason'], 'old failure')

    def test_global_single_instance_protection_and_release(self):
        with instance_lock(self.lock):
            result = self.execute(apply=True, limit=1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.client.get.call_count, 0)
        self.assertIn('Another rating backfill', result['errors'][0]['reason'])
        self.assertEqual(self.execute(limit=1)['status'], 'success')

    def test_403_and_invalid_json_stop_after_one_request(self):
        for value in (response(7, status=403), httpx.Response(200, content=b'<html>', request=httpx.Request('GET', 'https://gamebanana.com/test'))):
            self.client.get.side_effect = None
            self.client.get.return_value = value
            self.client.reset_mock()
            result = self.execute(apply=True, limit=2)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(self.client.get.call_count, 1)
            self.assertEqual(result['errors'][0]['http_status'], value.status_code)
            if value.status_code == 403:
                self.assertIsNotNone(result['not_before'])
                self.client.reset_mock()
                blocked = self.execute(apply=True, limit=2)
                self.assertEqual(blocked['totals']['requests'], 0)
                self.client.get.assert_not_called()
                # Independent malformed-JSON scenario: reset only this fixture's cooldown.
                (self.directory / 'source_pause.json').unlink()


if __name__ == '__main__':
    unittest.main()
