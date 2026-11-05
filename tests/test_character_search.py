import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from eryoutoolbox.database import initialize_database
from eryoutoolbox.ui_queries import query_mods
from eryoutoolbox.character_aliases import ALIASES


class CharacterSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'test.db';initialize_database(self.db)
        with closing(sqlite3.connect(self.db)) as c, c:
            for i,gid,title,author,cat,sub in [(1,8552,'Hu Tao costume','A','Skins','Hu Tao'),(2,8552,'Blue dress','B','Skins','Furina'),(3,18366,'Firefly suit','C','Skins','Firefly'),(4,19567,'New dress','Nicole Artist','Skins','Nicole'),(5,18366,'Hu Tao crossover','D','Skins','Hu Tao'),(6,18366,'胡桃中文原词','E','Other','Misc'),(7,21842,'Perlica','F','Skins','Perlica'),(8,23012,'Mint','G','Skins','Mint')]:
                c.execute("INSERT INTO mods(source,item_type,item_id,game_id,title,author_name,category,subcategory,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',?,?,?,?,?,?,'2026-01-01','2026-01-01')",(i,gid,title,author,cat,sub))
    def tearDown(self):self.tmp.cleanup()
    def ids(self,term,**kw):return [r['item_id'] for r in query_mods(self.db,search=term,**kw)['items']]
    def test_four_required_names(self):
        for name,wanted in [('胡桃',1),('芙宁娜',2),('流萤',3),('妮可',4)]:self.assertIn(wanted,self.ids(name))
    def test_game_scoping_and_original_keyword(self):
        self.assertEqual(set(self.ids('胡桃')),{1,6});self.assertEqual(self.ids('胡桃',game_id=18366),[6]);self.assertEqual(self.ids('芙宁娜',game_id=19567),[])
    def test_english_id_category_author_and_empty(self):
        for word,wanted in [('Hu Tao',1),('Furina',2),('Nicole Artist',4),('Skins',3),('3',3)]:self.assertIn(wanted,self.ids(word))
        self.assertEqual(self.ids('没有该角色作品'),[])
    def test_pagination_filters_and_no_write(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        page=query_mods(self.db,search='胡桃',limit=1,offset=1)
        self.assertEqual(page['total_count'],2);self.assertEqual(len(page['items']),1)
        self.assertEqual(self.ids('芙宁娜',category='UI'),[])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),before)
    def test_six_games_and_unknown_literal(self):
        self.assertEqual(len(ALIASES),6);self.assertEqual(self.ids('佩丽卡'),[7]);self.assertEqual(self.ids('薄荷'),[8]);self.assertEqual(self.ids("' OR 1=1 --"),[])

    def test_short_full_english_and_game_isolation(self):
        with closing(sqlite3.connect(self.db)) as c,c:
            for i,gid in [(9,19567),(10,8552)]:
                c.execute("INSERT INTO mods(source,item_type,item_id,game_id,title,subcategory,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',?,?,'Dress','Jane Doe','x','x')",(i,gid))
        self.assertEqual(self.ids('简'),[9]);self.assertEqual(self.ids('简·杜'),[9])
        self.assertEqual(set(self.ids('Jane Doe')),{9,10})
        self.assertEqual(self.ids('简',game_id=8552),[])

    def test_empty_search_explains_alias_and_remaining_filters(self):
        filtered=query_mods(self.db,search='芙宁娜',subcategory='Jane Doe')
        self.assertEqual(filtered['total_count'],0);self.assertTrue(filtered['search_info']['alias_known']);self.assertEqual(filtered['search_info']['unfiltered_count'],1)
        unknown=query_mods(self.db,search='未命名的未知角色')
        self.assertFalse(unknown['search_info']['alias_known']);self.assertEqual(unknown['search_info']['unfiltered_count'],0)
