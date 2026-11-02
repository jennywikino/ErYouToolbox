import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from repair_previews import audit,repair
from backfill_previews import GAMES
from eryoutoolbox.database import initialize_database,connect_database

class RepairTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=self.root/'data/test.db';initialize_database(self.db);self.game=GAMES[0];self.calls=[]
  c=connect_database(self.db)
  for i,g in enumerate(GAMES,1):
   c.execute("INSERT INTO mods(source,item_type,item_id,game_id,title,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',?,?, 'Keep','now','now')",(i,g['game_id']))
  c.execute("INSERT INTO user_states(source,item_type,item_id,is_read,note,updated_at) VALUES('gamebanana','Mod',1,1,'keep','now')")
  c.execute("INSERT INTO author_subscriptions VALUES('gamebanana',7,'Keep','now')");c.commit();c.close()
  self.payload={'_idRow':1,'_aGame':{'_idRow':self.game['game_id']},'_aPreviewMedia':{'_aImages':[{'_sBaseUrl':'https://images.gamebanana.com/img/ss/mods','_sFile':'sample.jpg','_sFile530':'530-90_sample.jpg','_sFile100':'100-90_sample.jpg'}]}}
 def tearDown(self):self.temp.cleanup()
 def client(self,status=200):
  def handle(req):self.calls.append(str(req.url));return httpx.Response(status,json=self.payload,headers={'Retry-After':'60'})
  return httpx.Client(transport=httpx.MockTransport(handle))
 def run_repair(self,apply=False,status=200):
  with self.client(status) as client,patch('repair_previews.time.sleep'):return repair(self.root,self.db,self.game,client=client,apply=apply)
 def test_audit_six_games_and_no_writes(self):
  before=self.db.read_bytes();result=audit(self.db)
  self.assertEqual(result['missing_total'],6);self.assertEqual(len(result['games']),6);self.assertEqual(before,self.db.read_bytes())
 def test_dry_run_exact_identity_and_originals(self):
  before=self.db.read_bytes();result=self.run_repair()
  self.assertEqual(result['to_update'],[1]);self.assertEqual(result['requests'],1)
  self.assertIn('/Mod/1/ProfilePage',self.calls[0]);self.assertEqual(before,self.db.read_bytes());self.assertFalse((self.root/'logs/preview_repairs/state.json').exists())
 def test_apply_idempotent_preserves_other_tables_and_fields(self):
  c=connect_database(self.db);before=[tuple(r) for r in c.execute('SELECT * FROM user_states')];c.close()
  self.assertEqual(self.run_repair(True)['updated'],1);self.assertEqual(self.run_repair(True)['requests'],0)
  c=connect_database(self.db)
  self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM user_states')]);self.assertEqual(c.execute('SELECT COUNT(*) FROM author_subscriptions').fetchone()[0],1)
  self.assertEqual(c.execute('SELECT COUNT(*) FROM mod_events').fetchone()[0],0);self.assertEqual(c.execute('SELECT title FROM mods WHERE item_id=1').fetchone()[0],'Keep');c.close()
  self.assertEqual(len(list((self.db.parent/'backups').glob('*.db'))),1)
 def test_source_no_images_only_with_explicit_evidence(self):
  self.payload['_aPreviewMedia']['_aImages']=[]
  self.assertEqual(self.run_repair(True)['source_no_images'],[1]);self.assertEqual(self.run_repair(True)['requests'],0)
 def test_missing_media_is_failure(self):
  self.payload.pop('_aPreviewMedia');r=self.run_repair();self.assertEqual(len(r['failed']),1);self.assertFalse(r['source_no_images'])
 def test_identity_and_untrusted_image_rejected(self):
  self.payload['_idRow']=2;self.assertTrue(self.run_repair()['failed'])
  self.payload['_idRow']=1;self.payload['_aPreviewMedia']['_aImages'][0]['_sBaseUrl']='https://example.com/images'
  self.assertTrue(self.run_repair()['failed'])
 def test_429_and_403_are_not_empty_and_cooldown(self):
  r=self.run_repair(status=429);self.assertTrue(r['failed']);self.assertFalse(r['source_no_images']);self.assertEqual(self.run_repair()['status'],'cooldown')
 def test_backup_and_transaction_failure(self):
  before=self.db.read_bytes()
  with patch('repair_previews.verified_backup',side_effect=OSError('backup failed')):
   with self.assertRaises(OSError):self.run_repair(True)
  self.assertEqual(before,self.db.read_bytes())
  c=connect_database(self.db);c.execute("CREATE TRIGGER reject_image BEFORE UPDATE ON mods BEGIN SELECT RAISE(ABORT,'reject'); END");c.commit();c.close()
  import sqlite3
  with self.assertRaises(sqlite3.Error):self.run_repair(True)
  self.assertFalse((self.root/'logs/preview_repairs/state.json').exists())
 def test_thumbnail_upgrade(self):
  c=connect_database(self.db);c.execute('UPDATE mods SET preview_urls_json=? WHERE item_id=1',(json.dumps(['https://images.gamebanana.com/img/ss/mods/100-90_sample.jpg']),));c.commit();c.close()
  self.assertEqual(self.run_repair(True)['updated'],1)
 def test_timeout_can_resume_without_false_empty(self):
  def fail(req):raise httpx.ReadTimeout('offline')
  with httpx.Client(transport=httpx.MockTransport(fail)) as client:
   r=repair(self.root,self.db,self.game,client=client)
  self.assertTrue(r['failed']);self.assertFalse(r['source_no_images']);self.assertEqual(self.run_repair()['to_update'],[1])

 def test_http_404_500_and_403_classified_as_failures(self):
  for status in (404,500,403):
   r=self.run_repair(status=status)
   self.assertEqual(r['requests'],1);self.assertEqual(r['failed'][0]['http_status'],status);self.assertFalse(r['source_no_images'])

 def test_mixed_high_and_low_resolution_is_conservatively_skipped(self):
  c=connect_database(self.db)
  images=[{'image_url':'https://images.gamebanana.com/img/ss/mods/full.jpg','thumbnail_url':'https://images.gamebanana.com/img/ss/mods/530-90_full.jpg'},'https://images.gamebanana.com/img/ss/mods/100-90_other.jpg']
  c.execute('UPDATE mods SET preview_urls_json=? WHERE item_id=1',(json.dumps(images),));c.commit();c.close()
  before=self.db.read_bytes();r=self.run_repair(True)
  self.assertEqual(r['updated'],0);self.assertEqual(self.db.read_bytes(),before)

 def test_all_nonimage_columns_tables_and_cursor_preserved(self):
  c=connect_database(self.db)
  c.execute("INSERT INTO sync_runs(source,game_id,started_at,status,error_summary) VALUES('gamebanana',8552,'now','success','{}')");c.commit()
  before=dict(c.execute('SELECT * FROM mods WHERE item_id=1').fetchone());before.pop('preview_urls_json')
  others={t:[tuple(r) for r in c.execute('SELECT * FROM '+t)] for t in ('user_states','author_subscriptions','mod_events','sync_runs')};c.close()
  self.run_repair(True);c=connect_database(self.db)
  after=dict(c.execute('SELECT * FROM mods WHERE item_id=1').fetchone());after.pop('preview_urls_json');self.assertEqual(before,after)
  for t,rows in others.items():self.assertEqual(rows,[tuple(r) for r in c.execute('SELECT * FROM '+t)])
  c.close()

 def test_shared_lock_and_limits(self):
  from backfill_content_ratings import instance_lock
  with instance_lock(self.root/'logs/content_ratings/instance.lock'):
   with self.assertRaises(RuntimeError):self.run_repair()
  with self.assertRaises(ValueError):repair(self.root,self.db,self.game,limit=21)

 def test_preflight_budget_and_stop(self):
  from preflight_previews import preflight
  from eryoutoolbox.database import backup_database
  backup_database(self.db,self.root/'data/eryoutoolbox.db')
  calls=[]
  def runner(root,db,game,**options):
   self.assertFalse(options['apply']);self.assertEqual(options['limit'],10);calls.append(game)
   return {'game':game,'status':'success','requests':10,'processed':[],'obtained_images':[],'failed':[],'to_update':[]}
  report,_=preflight(self.root,online=True,runner=runner)
  self.assertEqual(report['requests'],60);self.assertEqual(len(calls),6);self.assertTrue(report['business_data_unchanged'])
  def denied(root,db,game,**options):return {'game':game,'status':'partial','requests':1,'failed':[{'http_status':403}]}
  report,_=preflight(self.root,online=True,runner=denied)
  self.assertEqual(report['requests'],1);self.assertEqual(len(report['unexecuted_games']),5)

 def test_committed_failure_queue_resumes_after_interval(self):
  import time
  started=time.time();self.run_repair(True,status=500)
  state=json.loads((self.root/'logs/preview_repairs/state.json').read_text())
  self.assertEqual(state['database'],'data/test.db');self.assertEqual(state['items']['1']['status'],'failed')
  self.assertEqual(self.run_repair(True)['requests'],0)
  with patch('repair_previews.time.time',return_value=started+3602):
   self.assertEqual(self.run_repair(True)['updated'],1)

if __name__=='__main__':unittest.main()
