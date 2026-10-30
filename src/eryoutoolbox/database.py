"""SQLite foundation for ErYouToolbox.

All persisted timestamps use UTC ISO-8601 text (YYYY-MM-DDTHH:MM:SSZ).
GameBanana source epoch timestamps should be converted to this form at the
database boundary while retaining their source meaning in separate columns.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3


SCHEMA_VERSION = 3
BUSY_TIMEOUT_MS = 5000

MIGRATIONS = {
    3: ('ALTER TABLE user_states ADD COLUMN first_viewed_at TEXT',),
    2: ("""CREATE TABLE author_subscriptions (
        source TEXT NOT NULL, author_id INTEGER NOT NULL CHECK(author_id>0),
        display_name TEXT, followed_at TEXT NOT NULL,
        PRIMARY KEY(source,author_id))""",),
    1: (
        """CREATE TABLE IF NOT EXISTS mods (
            source TEXT NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            game_id INTEGER,
            game_name TEXT,
            title TEXT,
            original_url TEXT,
            author_id INTEGER,
            author_name TEXT,
            author_url TEXT,
            created_at TEXT,
            modified_at TEXT,
            updated_at TEXT,
            version TEXT,
            category TEXT,
            subcategory TEXT,
            tags_json TEXT,
            preview_urls_json TEXT,
            content_rating_status TEXT NOT NULL DEFAULT 'UNKNOWN'
                CHECK (content_rating_status IN ('UNKNOWN', 'SAFE', 'ADULT', 'OTHER')),
            raw_metadata_json TEXT,
            first_seen_at TEXT NOT NULL,
            last_checked_at TEXT NOT NULL,
            PRIMARY KEY (source, item_type, item_id)
        )""",
        """CREATE TABLE IF NOT EXISTS user_states (
            source TEXT NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
            is_favorite INTEGER NOT NULL DEFAULT 0 CHECK (is_favorite IN (0, 1)),
            is_ignored INTEGER NOT NULL DEFAULT 0 CHECK (is_ignored IN (0, 1)),
            workflow_status TEXT NOT NULL DEFAULT 'none'
                CHECK (workflow_status IN ('none', 'to_contact', 'to_repost', 'published')),
            note TEXT,
            published_url TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (source, item_type, item_id),
            FOREIGN KEY (source, item_type, item_id)
                REFERENCES mods (source, item_type, item_id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS mod_events (
            event_id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN ('first_seen', 'metadata_changed', 'source_updated')),
            occurred_at TEXT,
            detected_at TEXT NOT NULL,
            event_data_json TEXT,
            FOREIGN KEY (source, item_type, item_id)
                REFERENCES mods (source, item_type, item_id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS sync_runs (
            run_id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            game_id INTEGER,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
            request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
            fetched_count INTEGER NOT NULL DEFAULT 0 CHECK (fetched_count >= 0),
            deduplicated_count INTEGER NOT NULL DEFAULT 0 CHECK (deduplicated_count >= 0),
            error_summary TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_mods_game_checked ON mods (game_id, last_checked_at)",
        "CREATE INDEX IF NOT EXISTS idx_mod_events_mod ON mod_events (source, item_type, item_id, detected_at)",
        "CREATE INDEX IF NOT EXISTS idx_sync_runs_game_started ON sync_runs (game_id, started_at)",
    ),
}


def connect_database(path: str | Path) -> sqlite3.Connection:
    """Open a configured SQLite connection. The caller owns and closes it."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA journal_mode = DELETE")
    return connection


def initialize_database(path: str | Path, *, before_migration=None) -> None:
    """Create missing schema objects and apply known migrations atomically."""
    connection = connect_database(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} is newer than supported version {SCHEMA_VERSION}."
            )
        connection.execute("BEGIN IMMEDIATE")
        try:
            if 0 < version < SCHEMA_VERSION:
                if before_migration is None:
                    raise RuntimeError('Explicit verified backup required; run scripts/migrate_subscriptions.py --apply')
                before_migration()
            for migration_version in range(version + 1, SCHEMA_VERSION + 1):
                statements = MIGRATIONS.get(migration_version)
                if statements is None:
                    raise RuntimeError(f"No migration is defined for schema version {migration_version}.")
                for statement in statements:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {migration_version}")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    finally:
        connection.close()


def backup_database(source_path: str | Path, target_path: str | Path) -> None:
    """Back up a database using SQLite's online backup API to an explicit target."""
    source = Path(source_path).resolve()
    target = Path(target_path).resolve()
    if source == target:
        raise ValueError("Backup target must differ from the source database path.")
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = connect_database(source)
    target_connection: sqlite3.Connection | None = None
    try:
        target_connection = sqlite3.connect(target)
        source_connection.backup(target_connection)
    finally:
        if target_connection is not None:
            target_connection.close()
        source_connection.close()
