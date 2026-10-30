import sys,json,sqlite3,tempfile
from pathlib import Path
from datetime import datetime,timezone
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eryoutoolbox.database import initialize_database,MIGRATIONS
from eryoutoolbox.read_states import set_read,get_state
from eryoutoolbox.subscriptions import migrate,set_follow
from eryoutoolbox.ui_queries import query_mods
from eryoutoolbox.importer import import_samples
from tests.test_backfill_previews import mod

class ReadStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.db=Path(self.temp.name)/'test.db';initialize_database(self.db)
        self.c=sqlite3.connect(self.db)
        for i in range(1,5):
            self.c.execute("INSERT INTO mods(source,item_type,item_id,game_id,author_id,title,author_name,created_at,first_seen_at,last_checked_at,raw_metadata_json) VALUES('gamebanana','Mod',?,?,7,?,'Author','2026-01-01','2026-01-01','2026-01-01',?)",(i,8552 if i<3 else 19567,f'Test {i}',json.dumps({'_snapshot_collected_at':'2026-01-01T00:00:00Z'})))
        self.c.execute("INSERT INTO user_states(source,item_type,item_id,is_favorite,note,updated_at) VALUES('gamebanana','Mod',1,1,'keep','now')");self.c.commit()
    def tearDown(self):self.c.close();self.temp.cleanup()
    def test_mark_repeat_unread_reopen_preserves_first_time(self):
        first=set_read(self.db,'gamebanana',1,True)
        self.assertTrue(first['is_read']);self.assertTrue(first['first_viewed_at'])
        set_read(self.db,'gamebanana',1,True,backup=lambda:self.fail('duplicate backup'))
        set_read(self.db,'gamebanana',1,False)
        self.assertFalse(get_state(self.db,'gamebanana',1)['is_read'])
        self.assertEqual(set_read(self.db,'gamebanana',1,True)['first_viewed_at'],first['first_viewed_at'])
    def test_filters_before_pagination_and_missing_states_unread(self):
        set_read(self.db,'gamebanana',1,True)
        self.assertEqual(query_mods(self.db,read_filter='unread')['total_count'],3)
        self.assertEqual(query_mods(self.db,read_filter='read',game_id=8552)['total_count'],1)
        self.assertEqual(query_mods(self.db,read_filter='unread',search='Test 1')['total_count'],0)
        a=query_mods(self.db,read_filter='unread',limit=1)['items'][0]['item_id']
        b=query_mods(self.db,read_filter='unread',limit=1,offset=1)['items'][0]['item_id']
        self.assertNotEqual(a,b)
    def test_subscription_read_filter(self):
        set_follow(self.db,'gamebanana',7,True);set_read(self.db,'gamebanana',3,True)
        self.assertEqual(query_mods(self.db,subscriptions_only=True,game_id=19567,read_filter='read')['total_count'],1)
    def test_mod_and_other_user_fields_unchanged(self):
        before=self.c.execute('SELECT * FROM mods').fetchall();set_read(self.db,'gamebanana',1,True)
        self.assertEqual(before,self.c.execute('SELECT * FROM mods').fetchall())
        self.assertEqual(self.c.execute('SELECT is_favorite,note FROM user_states WHERE item_id=1').fetchone(),(1,'keep'))
    def test_source_update_import_does_not_reset_read(self):
        self.c.execute("UPDATE mods SET updated_at='2026-01-01T00:00:00Z' WHERE item_id=1");self.c.commit()
        set_read(self.db,'gamebanana',1,True)
        c=sqlite3.connect(self.db);c.row_factory=sqlite3.Row
        record=mod(item_id=1,title='Changed title');record['updated_at']='2026-10-30T00:00:00Z'
        result=import_samples(c,[({'path':'fixture','captured_at':datetime(2026,10,30,tzinfo=timezone.utc)},[record])],dry_run=False)
        self.assertEqual(result['source_update_events'],1)
        c.close();self.assertTrue(get_state(self.db,'gamebanana',1)['is_read'])
    def legacy(self):
        self.c.execute('ALTER TABLE user_states DROP COLUMN first_viewed_at');self.c.execute('PRAGMA user_version=2');self.c.commit()
    def test_legacy_reading_and_explicit_migration(self):
        self.legacy();self.assertFalse(get_state(self.db,'gamebanana',1)['available'])
        self.assertEqual(query_mods(self.db,read_filter='unread')['total_count'],4)
        with self.assertRaises(RuntimeError):set_read(self.db,'gamebanana',1,True)
        migrate(self.db);self.assertTrue(get_state(self.db,'gamebanana',1)['available'])
        self.assertEqual(self.c.execute('SELECT note FROM user_states WHERE item_id=1').fetchone()[0],'keep')
    def test_migration_failure_rolls_back_column_and_version(self):
        self.legacy()
        with patch.dict(MIGRATIONS,{3:MIGRATIONS[3]+('INVALID SQL',)}):
            with self.assertRaises(sqlite3.Error):migrate(self.db)
        self.assertEqual(self.c.execute('PRAGMA user_version').fetchone()[0],2)
        self.assertNotIn('first_viewed_at',[r[1] for r in self.c.execute('PRAGMA table_info(user_states)')])
    def test_backup_failure_no_state_changes(self):
        def fail():raise OSError('backup failed')
        with self.assertRaises(OSError):set_read(self.db,'gamebanana',1,True,backup=fail)
        self.assertFalse(get_state(self.db,'gamebanana',1)['is_read'])
    def test_unknown_remote_or_invalid_id_rejected(self):
        for i in (0,True,'1',999):
            with self.assertRaises(ValueError):set_read(self.db,'gamebanana',i,True)
        with self.assertRaises(ValueError):set_read(self.db,'gamebanana',1,1)

if __name__=='__main__':unittest.main()
