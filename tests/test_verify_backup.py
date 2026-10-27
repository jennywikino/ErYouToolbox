from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.database import initialize_database  # noqa: E402
from verify_backup import verify_backup_restore  # noqa: E402


class BackupVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def create_database(self, name="source.db"):
        path = self.root / name
        initialize_database(path)
        connection = sqlite3.connect(path)
        connection.execute("INSERT INTO mods (source,item_type,item_id,first_seen_at,last_checked_at) VALUES (?,?,?,?,?)",
                           ("gamebanana", "Mod", 123, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
        connection.execute("INSERT INTO user_states (source,item_type,item_id,updated_at) VALUES (?,?,?,?)",
                           ("gamebanana", "Mod", 123, "2026-01-01T00:00:00Z"))
        connection.execute("INSERT INTO mod_events (source,item_type,item_id,event_type,detected_at) VALUES (?,?,?,?,?)",
                           ("gamebanana", "Mod", 123, "first_seen", "2026-01-01T00:00:00Z"))
        connection.execute("INSERT INTO sync_runs (source,game_id,started_at,status) VALUES (?,?,?,?)",
                           ("gamebanana", 8552, "2026-01-01T00:00:00Z", "success"))
        connection.commit()
        connection.close()
        return path

    def test_backup_restore_passes_and_all_table_counts_match(self):
        path = self.create_database()
        report = verify_backup_restore(path)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["integrity"], "ok")
        self.assertEqual(report["foreign_key_violations"], [])
        self.assertEqual(report["original"]["counts"], report["restored"]["counts"])
        self.assertEqual(report["original"]["counts"], {
            "mods": 1, "user_states": 1, "mod_events": 1, "sync_runs": 1})
        self.assertEqual(report["original"]["user_version"], report["restored"]["user_version"])

    def test_source_database_bytes_remain_unchanged(self):
        report = verify_backup_restore(self.create_database())
        self.assertTrue(report["original_unchanged"])

    def test_corrupt_database_reports_failure(self):
        path = self.root / "corrupt.db"
        path.write_bytes(b"not a SQLite database")
        report = verify_backup_restore(path)
        self.assertFalse(report["passed"])
        self.assertIsNotNone(report["error"])
        self.assertTrue(report["original_unchanged"])

    def test_foreign_key_violation_reports_failure(self):
        path = self.create_database("foreign-key.db")
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("INSERT INTO user_states (source,item_type,item_id,updated_at) VALUES (?,?,?,?)",
                           ("gamebanana", "Mod", 999, "2026-01-01T00:00:00Z"))
        connection.commit()
        connection.close()
        report = verify_backup_restore(path)
        self.assertFalse(report["passed"])
        self.assertTrue(report["foreign_key_violations"])
        self.assertEqual(report["integrity"], "ok")


if __name__ == "__main__":
    unittest.main()
