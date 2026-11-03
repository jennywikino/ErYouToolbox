"""F3 regressions: temporary libraries only; no source network."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import httpx
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eryoutoolbox.database import initialize_database
from eryoutoolbox.ui_queries import query_mods,query_categories
from eryoutoolbox.popular import link_local
from eryoutoolbox.authors import fill_one
from auto_sync import AutoSync,DEFAULTS,atomic_json
from eryoutoolbox.source_detail import SourceDetail,summary


class F3Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.db=self.root/'data/eryoutoolbox.db';initialize_database(self.db)
 def tearDown(self):self.temp.cleanup()
 def seed(self):
  with closing(sqlite3.connect(self.db)) as c, c:
   for i,g,cat,sub in [(1,8552,'Skins','A'),(2,8552,'Skins','B'),(3,19567,'UI',None)]:
    c.execute("INSERT INTO mods(source,item_type,item_id,game_id,category,subcategory,first_seen_at,last_checked_at,raw_metadata_json) VALUES('gamebanana','Mod',?,?,?,?,'x','x',?)",(i,g,cat,sub,json.dumps({'_aContentRatings':{'pn':'Partial Nudity'}})))
 def test_category_counts_filters_paginate_readonly(self):
  self.seed();before=self.db.read_bytes()
  self.assertEqual(sum(r['count'] for r in query_categories(self.db)['items']),3)
  self.assertEqual(len(query_categories(self.db,8552)['items']),2)
  result=query_mods(self.db,game_id=8552,category='Skins',limit=1)
  self.assertEqual(result['total_count'],2);self.assertEqual(len(result['items']),1)
  self.assertEqual(query_mods(self.db,category='UI',game_id=8552)['total_count'],0)
  self.assertEqual(query_mods(self.db,category='Skins',subcategory='A')['items'][0]['item_id'],1)
  self.assertEqual(query_mods(self.db,category="Skins' OR 1=1 --")['total_count'],0)
  self.assertEqual(before,self.db.read_bytes())
 def test_popular_keeps_local_verified_labels(self):
  self.seed();result=link_local(self.db,{'items':[{'item_id':1,'source_ratings':{'codes':['UNKNOWN'],'verification':'unverified_labels'}},{'item_id':99,'source_ratings':{'codes':['UNKNOWN'],'verification':'unverified_labels'}}]})
  self.assertEqual(result['items'][0]['source_ratings']['codes'],['pn'])
  self.assertEqual(result['items'][1]['source_ratings']['codes'],['UNKNOWN'])
 def test_avatar_fill_serial_bounded(self):
  authors=[{'source':'gamebanana','author_id':i} for i in (1,2,3)]
  def member(*args,**kwargs):return {'avatar_url':'url'} if kwargs.get('fetch') else {'avatar_url':None}
  with patch('eryoutoolbox.authors._next_fill',0),patch('eryoutoolbox.authors.member',side_effect=member) as call:
   fill_one(self.root,authors);fill_one(self.root,authors)
  self.assertEqual(sum(bool(c.kwargs.get('fetch')) for c in call.call_args_list),1)
 def test_configured_false_then_persisted_no_override(self):
  auto=AutoSync(self.root,self.db,[],state_dir=self.root/'device')
  self.assertFalse(auto.status()['configured'])
  auto.configure({**DEFAULTS,'mode':'off','interval_hours':3})
  self.assertTrue(auto.status()['configured'])
  fresh=AutoSync(self.root,self.db,[],state_dir=self.root/'device')
  self.assertEqual(fresh.settings()['mode'],'off')
 def test_due_time_uses_clock_not_poll_time(self):
  auto=AutoSync(self.root,self.db,[],state_dir=self.root/'device')
  auto.configure({**DEFAULTS,'mode':'check','interval_hours':3})
  atomic_json(auto.directory/'last_run.json',{'status':'success','started_epoch':100,'started_at':'x'})
  with patch('auto_sync.time.time',return_value=99999):
   self.assertEqual(auto.status()['next_due'],'1970-01-01T03:01:40+00:00')
 def detail(self,**changes):
  return {'_idRow':1,'_sProfileUrl':'https://gamebanana.com/mods/1','_aGame':{'_idRow':8552},'_sName':'Test','_nLikeCount':0,'_aContentRatings':{'pn':'Partial Nudity'},**changes}
 def client(self,record,status=200,headers=None):
  c=Mock();c.get.return_value=httpx.Response(status,json=record,headers=headers,request=httpx.Request('GET','https://gamebanana.com/test'));return c
 def test_remote_detail_cache_and_no_db_write(self):
  before=self.db.read_bytes();client=self.client(self.detail());api=SourceDetail(client)
  first=api.fetch(1,{'game_id':8552});api.fetch(1,{'game_id':8552})
  self.assertEqual(client.get.call_count,1);self.assertFalse(first['is_local'])
  self.assertEqual(first['metrics'],{'likes':0});self.assertEqual(first['source_ratings']['codes'],['pn'])
  self.assertEqual(self.db.read_bytes(),before)
 def test_detail_identity_and_game_required(self):
  for value in [self.detail(_idRow=2),self.detail(_aGame={'_idRow':19567}),self.detail(_sProfileUrl='https://evil.test/mods/1')]:
   with self.assertRaises(ValueError):SourceDetail(self.client(value)).fetch(1,{'game_id':8552})
 def test_detail_429_and_403_cooldown(self):
  for status in (403,429):
   c=self.client({},status,{'Retry-After':'90'});api=SourceDetail(c)
   for _ in range(2):
    with self.assertRaises(RuntimeError):api.fetch(1,{'game_id':8552})
   self.assertEqual(c.get.call_count,1)
 def test_detail_timeout_and_bad_json(self):
  c=Mock();c.get.side_effect=httpx.ReadTimeout('offline')
  with self.assertRaises(httpx.ReadTimeout):SourceDetail(c).fetch(1,{'game_id':8552})
  c.get.side_effect=None;c.get.return_value=httpx.Response(200,text='not-json',request=httpx.Request('GET','https://gamebanana.com'))
  with self.assertRaises(ValueError):SourceDetail(c).fetch(1,{'game_id':8552})
 def test_summary_safe_text_null_metrics_and_files(self):
  result=summary({'_sText':'<p>Hello</p><script>evil()</script><li>World</li>','_nPostCount':0,'_nViewCount':None,'_aFiles':[{'_sFile':'file.zip','_nDownloadCount':3,'_tsDateAdded':1,'_sDownloadUrl':'https://do-not-expose.test'}]})
  self.assertEqual(result['metrics'],{'comments':0});self.assertNotIn('evil()',result['description'])
  self.assertIn('Hello',result['description']);self.assertEqual(result['file_count'],1)
  self.assertNotIn('_sDownloadUrl',str(result))

if __name__=='__main__':unittest.main()
