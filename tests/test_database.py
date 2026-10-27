from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eryoutoolbox.database import backup_database, connect_database, initialize_database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "data" / "test.db"
        initialize_database(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_first_initialization_creates_four_tables_and_version(self):
        connection = connect_database(self.db_path)
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"mods", "user_states", "mod_events", "sync_runs"}.issubset(tables))
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "delete")
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            connection.close()

    def test_repeated_initialization_preserves_existing_data(self):
        connection = connect_database(self.db_path)
        connection.execute("INSERT INTO mods (source, item_type, item_id, first_seen_at, last_checked_at) VALUES (?, ?, ?, ?, ?)",
                           ("gamebanana", "Mod", 42, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
        connection.commit()
        connection.close()
        initialize_database(self.db_path)
        connection = connect_database(self.db_path)
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM mods WHERE item_id=42").fetchone()[0], 1)
        finally:
            connection.close()

    def test_composite_unique_key_and_null_fields(self):
        connection = connect_database(self.db_path)
        row = ("gamebanana", "Mod", 5, None, None, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
        connection.execute("INSERT INTO mods (source,item_type,item_id,title,author_name,first_seen_at,last_checked_at) VALUES (?,?,?,?,?,?,?)", row)
        connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO mods (source,item_type,item_id,first_seen_at,last_checked_at) VALUES (?,?,?,?,?)",
                               ("gamebanana", "Mod", 5, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
        self.assertIsNone(connection.execute("SELECT author_name FROM mods WHERE item_id=5").fetchone()[0])
        connection.close()

    def test_foreign_key_constraint(self):
        connection = connect_database(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO user_states (source,item_type,item_id,updated_at) VALUES (?,?,?,?)",
                               ("gamebanana", "Mod", 404, "2026-01-01T00:00:00Z"))
        connection.close()

    def test_backup_can_be_opened_and_read(self):
        connection = connect_database(self.db_path)
        connection.execute("INSERT INTO mods (source,item_type,item_id,first_seen_at,last_checked_at) VALUES (?,?,?,?,?)",
                           ("gamebanana", "Mod", 88, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
        connection.commit()
        connection.close()
        backup_path = self.root / "backup" / "copy.db"
        backup_database(self.db_path, backup_path)
        restored = sqlite3.connect(backup_path)
        try:
            self.assertEqual(restored.execute("SELECT item_id FROM mods").fetchone()[0], 88)
        finally:
            restored.close()

    def test_connection_can_be_closed(self):
        connection = connect_database(self.db_path)
        connection.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
