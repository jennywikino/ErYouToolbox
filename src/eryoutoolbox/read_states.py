"""Local MOD read state; source+item_id resolves only item_type=Mod."""
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
from .ui_queries import readonly_connection
from .subscriptions import verified_backup

def validate(source,item_id):
    if not isinstance(source,str) or not source.strip() or len(source)>80 or type(item_id) is not int or not 0<item_id<2**63:
        raise ValueError('Invalid MOD source or ID')

def available(c):return any(r[1]=='first_viewed_at' for r in c.execute('PRAGMA table_info(user_states)'))

def get_state(database,source,item_id):
    validate(source,item_id)
    c=readonly_connection(database)
    try:
        if not c.execute("SELECT 1 FROM mods WHERE source=? AND item_type='Mod' AND item_id=?",(source,item_id)).fetchone():raise ValueError('MOD is not stored locally')
        ready=available(c)
        row=c.execute('SELECT is_read'+(',first_viewed_at' if ready else '')+" FROM user_states WHERE source=? AND item_type='Mod' AND item_id=?",(source,item_id)).fetchone()
        return {'available':ready,'is_read':bool(row and row[0]),'first_viewed_at':row[1] if row and ready else None}
    finally:c.close()

def set_read(database,source,item_id,is_read,backup=None):
    validate(source,item_id)
    if type(is_read) is not bool:raise ValueError('is_read must be boolean')
    c=sqlite3.connect(Path(database).resolve().as_uri()+'?mode=rw',uri=True,timeout=5)
    try:
        c.execute('PRAGMA foreign_keys=ON');c.execute('BEGIN IMMEDIATE')
        if not available(c):raise RuntimeError('Read-state timestamp requires scripts/migrate_read_states.py --apply')
        if not c.execute("SELECT 1 FROM mods WHERE source=? AND item_type='Mod' AND item_id=?",(source,item_id)).fetchone():raise ValueError('MOD is not stored locally')
        row=c.execute("SELECT is_read,first_viewed_at FROM user_states WHERE source=? AND item_type='Mod' AND item_id=?",(source,item_id)).fetchone()
        if row and bool(row[0])==is_read and (not is_read or row[1]):
            c.commit();return {'available':True,'is_read':is_read,'first_viewed_at':row[1]}
        if not row and not is_read:
            c.commit();return {'available':True,'is_read':False,'first_viewed_at':None}
        (backup or (lambda:verified_backup(database)))()
        stamp=datetime.now(timezone.utc).isoformat()
        c.execute("INSERT INTO user_states(source,item_type,item_id,is_read,updated_at,first_viewed_at) VALUES(?,'Mod',?,?,?,?) ON CONFLICT(source,item_type,item_id) DO UPDATE SET is_read=excluded.is_read,updated_at=excluded.updated_at,first_viewed_at=COALESCE(user_states.first_viewed_at,excluded.first_viewed_at)",
                  (source,item_id,int(is_read),stamp,stamp if is_read else None))
        c.commit()
    except BaseException:c.rollback();raise
    finally:c.close()
    return get_state(database,source,item_id)
