import unittest,json,sqlite3
from pathlib import Path
from unittest.mock import patch
import test_author_updates as helpers
from eryoutoolbox.author_updates import run_rotation,baseline,preview
from backfill_content_ratings import instance_lock

class RotationTests(unittest.TestCase):
 def setUp(self):
  helpers.AuthorChecks.setUp(self)
  self.root=Path(self.temp.name);(self.root/'config').mkdir()
  (self.root/'config/games.json').write_text(json.dumps({'games':[{'game_id':8552,'name':'Game'}]}),encoding='utf-8')
  def get(url,params=None):
   if params:return helpers.reply([['Mod',params['userid']*100+i] for i in range(3)])
   item=int(url.split('/')[-2]);return helpers.reply({**self.profile,'_idRow':item,'_aSubmitter':{'_idRow':item//100}})
  self.client.get.side_effect=get
 tearDown=helpers.AuthorChecks.tearDown
 def scan(self,**kwargs):
  with patch('eryoutoolbox.author_updates.time.sleep'):
   return run_rotation(self.db,self.root,client=self.client,**kwargs)
 def test_five_authors_fair_and_unfollow(self):
  c=sqlite3.connect(self.db)
  for a in [8,9,10,11]:c.execute("INSERT INTO author_subscriptions VALUES('gamebanana',?,?,'now')",(a,str(a)))
  c.commit();c.close();seen=[]
  for _ in range(3):seen.extend(a['author_id'] for a in self.scan()['authors'])
  self.assertEqual(seen,[7,8,9,10,11,7])
  c=sqlite3.connect(self.db);c.execute('DELETE FROM author_subscriptions WHERE author_id=7');c.commit();c.close()
  self.assertNotIn(7,[a['author_id'] for a in self.scan()['authors']])
 def test_partial_commit_resume_and_historical_events(self):
  first=self.scan(apply=True,details=1);self.assertEqual(first['status'],'partial')
  c=sqlite3.connect(self.db);self.assertIsNone(baseline(c,7)['checked_at']);self.assertEqual(c.execute("SELECT COUNT(*) FROM mod_events WHERE event_type='first_seen'").fetchone()[0],0);c.close()
  second=self.scan(apply=True,details=1);self.assertEqual(second['pending_count'],1)
  third=self.scan(apply=True,details=1);self.assertEqual(third['status'],'success')
  c=sqlite3.connect(self.db);self.assertIsNotNone(baseline(c,7)['checked_at']);self.assertEqual(c.execute('SELECT COUNT(*) FROM mods').fetchone()[0],4);c.close()
 def test_dryrun_no_rotation_or_database_write(self):
  before=self.db.read_bytes();self.scan(advance=False)
  self.assertEqual(before,self.db.read_bytes());self.assertFalse((self.root/'logs/author_updates/rotation.json').exists())
 def test_failed_author_does_not_starve_others(self):
  c=sqlite3.connect(self.db);c.execute("INSERT INTO author_subscriptions VALUES('gamebanana',8,'other','now')");c.commit();c.close()
  original=self.client.get.side_effect
  def get(url,params=None):
   if params and params['userid']==7:raise helpers.httpx.ReadTimeout('offline')
   return original(url,params)
  self.client.get.side_effect=get
  r=self.scan(apply=True);self.assertEqual([a['status'] for a in r['authors']],['failed','success'])
  c=sqlite3.connect(self.db);self.assertIsNone(baseline(c,7));self.assertIsNotNone(baseline(c,8));c.close()
 def test_rollback_queue_and_resume(self):
  with patch('eryoutoolbox.author_updates.verified_backup',side_effect=OSError('backup failed')):r=self.scan(apply=True)
  self.assertEqual(r['status'],'failed');self.assertEqual(len(json.loads((self.root/'logs/author_updates/rotation.json').read_text())['failures']['7']['pending_ids']),3)
  self.assertEqual(self.scan(apply=True)['status'],'success')
 def test_shared_lock_blocks_manual_preview(self):
  with instance_lock(self.root/'logs/content_ratings/instance.lock'):
   with self.assertRaises(RuntimeError):preview(self.db,self.root)
 def test_rate_limit_cooldown(self):
  self.client.get.side_effect=lambda *a,**k:helpers.reply({},429)
  r=self.scan();self.assertEqual(r['requests'],1)
  with self.assertRaises(ValueError):self.scan()
 def test_new_publication_after_baseline_and_repeat(self):
  from eryoutoolbox.author_updates import apply_report
  first=self.scan(advance=False)
  first['observed_at']='2026-01-01T00:00:00+00:00'
  for author in first['authors']:author['observed_at']=first['observed_at']
  apply_report(self.db,first)
  def get(url,params=None):
   if params:return helpers.reply([['Mod',799]])
   return helpers.reply({**self.profile,'_idRow':799,'_aSubmitter':{'_idRow':7},'_tsDateAdded':1770000000})
  self.client.get.side_effect=get
  result=self.scan(apply=True);self.assertEqual(result['applied'][0]['new_publications'],1)
  result=self.scan(apply=True);self.assertEqual(result['applied'][0]['new_events'],0)
  c=sqlite3.connect(self.db)
  try:self.assertEqual(c.execute("SELECT COUNT(*) FROM mod_events WHERE event_type='first_seen'").fetchone()[0],1)
  finally:c.close()
if __name__=='__main__':unittest.main()
