from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eryoutoolbox.database import backup_database, connect_database, initialize_database  # noqa: E402
from eryoutoolbox.importer import import_samples, load_sample  # noqa: E402


def captured(minutes: int = 0) -> str:
    return (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def record(item_id: int = 10, **overrides):
    value = {
        "source": "gamebanana", "item_type": "Mod", "item_id": item_id,
        "game_id": 8552, "game_name": "Genshin Impact", "title": "Title",
        "original_url": f"https://gamebanana.com/mods/{item_id}", "author_id": 5,
        "author_name": "Author", "author_url": "https://gamebanana.com/members/5",
        "created_at": "2025-12-01T00:00:00Z", "modified_at": None, "updated_at": None,
        "version": None, "category": "Characters", "subcategory": None,
        "tags": ["sample"], "preview_urls": ["https://images.example.test/p.jpg"],
        "content_rating_status": "UNKNOWN",
    }
    value.update(overrides)
    return value


def snapshot(record_list, minutes=0, filename="gamebanana_8552.json"):
    return ({"path": filename, "captured_at": datetime.fromisoformat(captured(minutes).replace("Z", "+00:00")),
             "captured_at_raw": captured(minutes)}, record_list)


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=ROOT)
        self.db_path = Path(self.temp_dir.name) / "test.db"
        initialize_database(self.db_path)
        self.connection = connect_database(self.db_path)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def count(self, table):
        return self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def import_one(self, value, minutes=0, dry_run=False):
        return import_samples(self.connection, [snapshot([value], minutes)], dry_run=dry_run)

    def test_first_insert_creates_mod_user_state_and_first_seen_event(self):
        result = self.import_one(record())
        self.assertEqual(result["inserted"], 1)
        self.assertEqual((self.count("mods"), self.count("user_states"), self.count("mod_events")), (1, 1, 1))

    def test_repeated_import_is_idempotent(self):
        self.import_one(record())
        result = self.import_one(record())
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(self.count("mods"), 1)

    def test_newer_title_change_updates_existing_mod(self):
        self.import_one(record())
        result = self.import_one(record(title="Changed"), minutes=1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(self.connection.execute("SELECT title FROM mods").fetchone()[0], "Changed")
        event = self.connection.execute("SELECT event_type,event_data_json FROM mod_events WHERE event_type='metadata_changed'").fetchone()
        self.assertIsNotNone(event)
        self.assertIn('"title"', event["event_data_json"])

    def test_missing_fields_do_not_clear_existing_values(self):
        self.import_one(record())
        result = self.import_one(record(title=None, author_name=None, tags=[], preview_urls=[]), minutes=1)
        row = self.connection.execute("SELECT title,author_name,tags_json,preview_urls_json FROM mods").fetchone()
        self.assertEqual(tuple(row), ("Title", "Author", '["sample"]', '["https://images.example.test/p.jpg"]'))
        self.assertEqual(result["unchanged"], 1)

    def test_composite_key_distinguishes_source(self):
        self.import_one(record())
        other = record(source="other")
        result = self.import_one(other)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(self.count("mods"), 2)

    def test_user_state_is_not_overwritten(self):
        self.import_one(record())
        self.connection.execute("UPDATE user_states SET is_read=1,is_favorite=1,note='keep',workflow_status='to_repost' ")
        self.connection.commit()
        self.import_one(record(title="New title"), minutes=1)
        state = self.connection.execute("SELECT is_read,is_favorite,note,workflow_status FROM user_states").fetchone()
        self.assertEqual(tuple(state), (1, 1, "keep", "to_repost"))

    def test_first_seen_timestamp_is_preserved(self):
        self.import_one(record())
        initial = self.connection.execute("SELECT first_seen_at FROM mods").fetchone()[0]
        self.import_one(record(title="Later"), minutes=1)
        self.assertEqual(self.connection.execute("SELECT first_seen_at FROM mods").fetchone()[0], initial)

    def test_reimport_does_not_duplicate_first_seen_event(self):
        self.import_one(record())
        self.import_one(record())
        self.assertEqual(self.count("mod_events"), 1)

    def test_only_modified_at_change_does_not_create_source_update(self):
        self.import_one(record(modified_at="2025-12-01T00:00:00Z"))
        self.import_one(record(modified_at="2025-12-02T00:00:00Z"), minutes=1)
        self.assertEqual(self.count("mod_events"), 1)

    def test_strictly_later_source_updated_at_creates_source_updated(self):
        self.import_one(record(updated_at="2025-12-01T00:00:00Z"))
        self.import_one(record(updated_at="2025-12-02T00:00:00Z"), minutes=1)
        events = self.connection.execute("SELECT event_type,occurred_at FROM mod_events ORDER BY event_id").fetchall()
        self.assertEqual([row["event_type"] for row in events], ["first_seen", "source_updated"])
        self.assertEqual(events[1]["occurred_at"], "2025-12-02T00:00:00Z")

    def test_same_source_updated_at_does_not_create_duplicate_event(self):
        value = record(updated_at="2025-12-01T00:00:00Z")
        self.import_one(value)
        self.import_one(value, minutes=1)
        self.assertEqual(self.count("mod_events"), 1)

    def test_first_non_null_updated_at_is_not_source_update(self):
        self.import_one(record(updated_at=None))
        self.import_one(record(updated_at="2025-12-02T00:00:00Z"), minutes=1)
        self.assertEqual(self.count("mod_events"), 1)

    def test_source_update_with_metadata_change_is_one_event(self):
        self.import_one(record(updated_at="2025-12-01T00:00:00Z"))
        self.import_one(record(updated_at="2025-12-02T00:00:00Z", title="New title"), minutes=1)
        events = self.connection.execute("SELECT event_type,event_data_json FROM mod_events ORDER BY event_id").fetchall()
        self.assertEqual([row["event_type"] for row in events], ["first_seen", "source_updated"])
        self.assertIn("metadata_changes", events[1]["event_data_json"])

    def test_invalid_identity_is_skipped(self):
        result = self.import_one(record(item_id=None))
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.count("mods"), 0)

    def test_transaction_rolls_back_on_sql_error(self):
        self.connection.execute("CREATE TRIGGER fail_event BEFORE INSERT ON mod_events BEGIN SELECT RAISE(ABORT, 'forced'); END")
        self.connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.import_one(record())
        self.assertEqual(self.count("mods"), 0)
        self.assertEqual(self.count("user_states"), 0)

    def test_event_insert_failure_rolls_back_mod_update(self):
        self.import_one(record())
        self.connection.execute("CREATE TRIGGER fail_metadata BEFORE INSERT ON mod_events WHEN NEW.event_type='metadata_changed' BEGIN SELECT RAISE(ABORT, 'forced'); END")
        self.connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.import_one(record(title="Should rollback"), minutes=1)
        self.assertEqual(self.connection.execute("SELECT title FROM mods").fetchone()[0], "Title")
        self.assertEqual(self.count("mod_events"), 1)

    def test_dry_run_does_not_write(self):
        result = self.import_one(record(), dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(self.count("mods"), 0)

    def test_unchanged_apply_does_not_call_backup(self):
        self.import_one(record())
        calls = []
        result = import_samples(self.connection, [snapshot([record()])], dry_run=False,
                                before_write=lambda: calls.append("backup"))
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(calls, [])

    def test_insert_and_update_call_backup_before_write(self):
        backup_path = Path(self.temp_dir.name) / "backup.db"
        result = import_samples(
            self.connection, [snapshot([record()])], dry_run=False,
            before_write=lambda: backup_database(self.db_path, backup_path),
        )
        self.assertEqual(result["inserted"], 1)
        self.assertTrue(backup_path.is_file())
        backup = sqlite3.connect(backup_path)
        try:
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM mods").fetchone()[0], 0)
        finally:
            backup.close()

        update_backup = Path(self.temp_dir.name) / "update-backup.db"
        result = import_samples(
            self.connection, [snapshot([record(title="Updated")], minutes=1)], dry_run=False,
            before_write=lambda: backup_database(self.db_path, update_backup),
        )
        self.assertEqual(result["updated"], 1)
        self.assertTrue(update_backup.is_file())

    def test_source_update_with_real_backup_api_completes_in_transaction(self):
        self.import_one(record(updated_at="2025-12-01T00:00:00Z"))
        backup_path = Path(self.temp_dir.name) / "source-update-backup.db"
        result = import_samples(
            self.connection,
            [snapshot([record(updated_at="2025-12-02T00:00:00Z")], minutes=1)],
            dry_run=False,
            before_write=lambda: backup_database(self.db_path, backup_path),
        )
        self.assertEqual(result["updated"], 1)
        self.assertTrue(backup_path.is_file())
        event_types = [row[0] for row in self.connection.execute("SELECT event_type FROM mod_events ORDER BY event_id")]
        self.assertEqual(event_types, ["first_seen", "source_updated"])

    def test_backup_failure_rolls_back_and_does_not_modify_database(self):
        with self.assertRaisesRegex(OSError, "backup failed"):
            import_samples(self.connection, [snapshot([record()])], dry_run=False,
                            before_write=lambda: (_ for _ in ()).throw(OSError("backup failed")))
        self.assertEqual(self.count("mods"), 0)
        self.assertEqual(self.count("user_states"), 0)

    def test_dry_run_never_calls_backup(self):
        def fail_if_called():
            raise AssertionError("dry run must not create backup")
        result = import_samples(self.connection, [snapshot([record()])], dry_run=True,
                                before_write=fail_if_called)
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.count("mods"), 0)

    def test_older_snapshot_cannot_overwrite_newer_data(self):
        self.import_one(record(title="New"), minutes=5)
        result = self.import_one(record(title="Old"), minutes=1)
        self.assertEqual(self.connection.execute("SELECT title FROM mods").fetchone()[0], "New")
        self.assertEqual(result["unchanged"], 1)
        self.assertTrue(any("Older sample" in item["reason"] for item in result["snapshot_warnings"]))

    def test_only_collector_named_sample_is_accepted(self):
        path = Path(self.temp_dir.name) / "arbitrary.json"
        path.write_text(json.dumps({"game": {"game_id": 1}, "records": []}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_sample(path)


if __name__ == "__main__":
    unittest.main()
