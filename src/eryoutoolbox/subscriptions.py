"""Local author subscriptions, isolated from source metadata and user states."""
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from .ui_queries import readonly_connection
from .database import backup_database, initialize_database

def ready(connection):
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='author_subscriptions'").fetchone() is not None

def status(database, source, author_id):
    c = readonly_connection(database)
    try:
        available = ready(c)
        followed = bool(available and c.execute('SELECT 1 FROM author_subscriptions WHERE source=? AND author_id=?', (source, author_id)).fetchone())
        return {'available': available, 'followed': followed}
    finally:
        c.close()

def verified_backup(database):
    target = Path(database).parent / 'backups' / ('subscriptions_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.db')
    if target.exists():
        raise FileExistsError(target)
    backup_database(database, target)
    c = readonly_connection(target)
    try:
        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or c.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Backup verification failed')
    finally:
        c.close()
    return target

def migrate(database):
    if not Path(database).is_file():
        raise FileNotFoundError(database)
    initialize_database(database, before_migration=lambda: verified_backup(database))

def set_follow(database, source, author_id, followed, backup=None):
    if (not isinstance(source, str) or not source.strip() or len(source)>80
            or type(author_id) is not int or not 0<author_id<2**63 or type(followed) is not bool):
        raise ValueError('Invalid source, author ID or followed flag')
    c = sqlite3.connect(Path(database).resolve().as_uri()+'?mode=rw', uri=True, timeout=5)
    try:
        c.execute('BEGIN IMMEDIATE')
        if not ready(c):
            raise RuntimeError('Subscriptions require explicit database migration')
        exists = c.execute('SELECT 1 FROM author_subscriptions WHERE source=? AND author_id=?', (source, author_id)).fetchone()
        if bool(exists) == followed:
            c.commit()
            return {'available': True, 'followed': followed, 'changed': False}
        row = c.execute('SELECT author_name FROM mods WHERE source=? AND author_id=? LIMIT 1', (source, author_id)).fetchone()
        if followed and row is None:
            raise ValueError('Author is not in the local library')
        (backup or (lambda: verified_backup(database)))()
        if followed:
            c.execute('INSERT INTO author_subscriptions VALUES(?,?,?,?)', (source, author_id, row[0], datetime.now(timezone.utc).isoformat()))
        else:
            c.execute('DELETE FROM author_subscriptions WHERE source=? AND author_id=?', (source, author_id))
        c.commit()
        return {'available': True, 'followed': followed, 'changed': True}
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()
