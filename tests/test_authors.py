import json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from eryoutoolbox.database import initialize_database
from eryoutoolbox.authors import author_list,member,avatar_url
from eryoutoolbox.ui_queries import query_mods
class AuthorsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'test.db';initialize_database(self.db)
 def tearDown(self):self.tmp.cleanup()
 def seed(self,n=1):
  c=sqlite3.connect(self.db)
  for i in range(1,n+1):
   c.execute("INSERT INTO author_subscriptions VALUES('gamebanana',?,'Same name','2026-01-01T00:00:00Z')",(i,))
   c.execute("INSERT INTO mods(source,item_type,item_id,author_id,author_name,game_id,created_at,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',? ,?,'Same name',8552,'2026-01-01T00:00:00Z','x','x')",(i,i))
  c.commit();c.close()
 def test_empty(self):self.assertEqual(author_list(self.db)['total_count'],0)
 def test_one(self):
  self.seed();r=author_list(self.db);self.assertEqual(r['followed_count'],1);self.assertEqual(r['items'][0]['mod_count'],1)
 def test_sixteen_same_name_and_paging(self):
  self.seed(16);a=author_list(self.db,limit=10);b=author_list(self.db,limit=10,offset=10)
  self.assertEqual(len(a['items'])+len(b['items']),16);self.assertEqual(len({r['author_id'] for r in a['items']+b['items']}),16)
  self.assertEqual(author_list(self.db,search='not found')['total_count'],0)
 def test_unfollow_and_no_mods(self):
  self.seed();c=sqlite3.connect(self.db);c.execute('DELETE FROM mods');c.commit();c.close()
  self.assertEqual(author_list(self.db)['items'][0]['mod_count'],0)
  c=sqlite3.connect(self.db);c.execute('DELETE FROM author_subscriptions');c.commit();c.close();self.assertEqual(author_list(self.db)['followed_count'],0)
 def test_author_source_game_exclusion_and_readonly(self):
  self.seed(2);c=sqlite3.connect(self.db)
  c.execute("INSERT INTO mods(source,item_type,item_id,author_id,game_id,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',3,1,19567,'x','x')")
  c.execute("INSERT INTO mods(source,item_type,item_id,author_id,game_id,first_seen_at,last_checked_at) VALUES('other','Mod',1,1,8552,'x','x')");c.commit();c.close();before=self.db.read_bytes()
  self.assertEqual(query_mods(self.db,author_source='gamebanana',author_id=1)['total_count'],2)
  self.assertEqual(query_mods(self.db,author_source='gamebanana',author_id=1,game_id=19567)['total_count'],1)
  self.assertEqual(query_mods(self.db,author_source='gamebanana',author_id=1,exclude_item_id=1)['items'][0]['item_id'],3)
  self.assertEqual(before,self.db.read_bytes())
 def test_no_other_works(self):
  self.seed();self.assertEqual(query_mods(self.db,author_source='gamebanana',author_id=1,exclude_item_id=1)['items'],[])
 def client(self,value):
  client=Mock();client.get.return_value=httpx.Response(200,json=value,request=httpx.Request('GET','https://api.gamebanana.com/Core/Item/Data'));return client
 def test_member_real_mapping_and_cache(self):
  client=self.client({'name':'Author','Url().sProfileUrl()':'https://gamebanana.com/members/7','Url().sAvatarUrl()':'https://images.gamebanana.com/img/av/test.png','Url().sHdAvatarUrl()':''})
  a=member(self.root,'gamebanana',7,client,True);b=member(self.root,'gamebanana',7,client,True)
  self.assertEqual(a['avatar_url'],b['avatar_url']);self.assertEqual(client.get.call_count,1)
 def test_missing_avatar_failure_and_identity(self):
  for value in [{'Url().sProfileUrl()':'https://gamebanana.com/members/8'},{'name':'A','Url().sProfileUrl()':'https://evil.test/7'}]:
   result=member(self.root,'gamebanana',8,self.client(value),True);self.assertIsNone(result['avatar_url'])
  client=Mock();client.get.side_effect=httpx.ReadTimeout('offline');self.assertIsNone(member(self.root,'gamebanana',9,client,True)['avatar_url'])
  member(self.root,'gamebanana',9,client,True);self.assertEqual(client.get.call_count,1)
 def test_list_cache_does_not_request(self):
  client=Mock();member(self.root,'gamebanana',7,client,False);client.get.assert_not_called()
 def test_url_validation(self):
  for url in ['javascript:alert(1)','https://evil.test/img/av/x.png','https://images.gamebanana.com@evil.test/img/av/x','https://images.gamebanana.com/img/av/../x','http://images.gamebanana.com/img/av/x']:
   self.assertIsNone(avatar_url(url))
if __name__=='__main__':unittest.main()
