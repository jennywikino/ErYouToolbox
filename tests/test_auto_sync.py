"""Automatic sync tests use temporary databases and mocked source requests only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from auto_sync import AutoSync,DEFAULTS,validate_root
from web_sync import WebSync
from manage_auto_sync import locator,manage
from eryoutoolbox.database import initialize_database,connect_database
from backfill_content_ratings import instance_lock

class AutomaticSyncTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=self.root/'data/eryoutoolbox.db';initialize_database(self.db)
  (self.root/'config').mkdir();shutil.copyfile(ROOT/'config/project_identity.json',self.root/'config/project_identity.json')
  self.games=[{'name':'Game','game_id':8552},{'name':'Other','game_id':19567}]
  self.auto=AutoSync(self.root,self.db,self.games,state_dir=self.root/'device')
 def tearDown(self):self.temp.cleanup()
 def configure(self,mode):self.auto.configure({**DEFAULTS,'mode':mode})
 def count(self,table):
  c=connect_database(self.db)
  try:return c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
  finally:c.close()
 def source(self,client,game,**kwargs):
  return {'records':[{'source':'gamebanana','item_type':'Mod','item_id':game['game_id'],'game_id':game['game_id'],'title':'New','author_id':7,'updated_at':'2026-01-01T00:00:00Z'}],
          'actual_record_count':1,'request_count':1,'collected_at':'2026-10-30T00:00:00Z','failure_reasons':[]}
 def run_auto(self,**kwargs):
  with patch('web_sync.collect_game',side_effect=self.source),patch('web_sync.time.sleep'):
   return self.auto.run(force=True,max_pages=1,**kwargs)
 def test_default_off(self):
  with patch('web_sync.collect_game') as request:
   self.assertEqual(self.auto.run()['status'],'disabled');request.assert_not_called()
  self.assertEqual(self.count('mods'),0)
 def test_check_no_database_checkpoint_backup(self):
  self.configure('check');result=self.run_auto()
  self.assertEqual(result['status'],'waiting');self.assertEqual(self.count('mods'),0);self.assertEqual(self.count('sync_runs'),0)
  self.assertFalse((self.db.parent/'backups').exists());self.assertEqual(WebSync(self.db,self.root,self.games).committed(),{})
 def test_apply_idempotent_restart_browser_not_needed(self):
  self.configure('apply');self.assertEqual(self.run_auto()['inserted'],2)
  self.assertEqual(self.run_auto()['inserted'],0);self.assertEqual(self.count('mods'),2);self.assertEqual(self.count('mod_events'),2)
  fresh=AutoSync(self.root,self.db,self.games,state_dir=self.root/'device');self.assertEqual(fresh.status()['last_run']['inserted'],0)
  self.assertEqual(len(list((self.db.parent/'backups').glob('*.db'))),1)
 def test_duplicate_tasks_share_lock(self):
  self.configure('apply')
  with instance_lock(self.root/'logs/content_ratings/instance.lock'):
   with self.assertRaises(RuntimeError):self.auto.run(force=True)
  self.assertEqual(self.count('mods'),0)
 def test_429_cooldown_no_immediate_retry(self):
  self.configure('apply')
  def limited(client,game,**kwargs):
   result=self.source(client,game,**kwargs);result.update(records=[],actual_record_count=0,failure_reasons=[{'http_status':429,'reason':'Retry-After respected by collector'}]);return result
  with patch('web_sync.collect_game',side_effect=limited) as requests,patch('web_sync.time.sleep'):
   result=self.auto.run(force=True,max_pages=1);self.assertEqual(result['requests'],1)
   self.assertEqual(self.auto.run(force=True,max_pages=1)['status'],'cooldown');self.assertEqual(requests.call_count,1)
  self.assertEqual(self.count('mods'),0)
 def test_timeout_partial_resume(self):
  self.configure('apply')
  def source(client,game,**kwargs):
   result=self.source(client,game,**kwargs)
   if game['game_id']==8552:result.update(records=[],actual_record_count=0,failure_reasons=[{'http_status':None,'reason':'ReadTimeout'}])
   return result
  with patch('web_sync.collect_game',side_effect=source),patch('web_sync.time.sleep'):
   result=self.auto.run(force=True,max_pages=1)
  self.assertEqual(result['status'],'partial');self.assertEqual(self.count('mods'),1)
  self.assertEqual(self.run_auto()['inserted'],1);self.assertEqual(self.count('mods'),2)
 def test_backup_failure_rolls_back(self):
  self.configure('apply')
  with patch('web_sync.backup_database',side_effect=OSError('backup failed')):result=self.run_auto()
  self.assertEqual(result['status'],'failed');self.assertEqual(self.count('mods'),0);self.assertEqual(self.count('sync_runs'),0)
 def test_apply_only_new_or_reliable_source_update(self):
  self.configure('apply');self.run_auto()
  # A title-only change must not become an automatic source update.
  def changed(client,game,**kwargs):
   r=self.source(client,game,**kwargs);r['collected_at']='2026-11-01T00:00:00Z';r['records'][0]['title']='Changed';return r
  with patch('web_sync.collect_game',side_effect=changed),patch('web_sync.time.sleep'):
   result=self.auto.run(force=True,max_pages=1)
  self.assertEqual(result['source_updated'],0);c=connect_database(self.db)
  self.assertEqual(c.execute('SELECT title FROM mods LIMIT 1').fetchone()[0],'New');c.close()
  def updated(client,game,**kwargs):
   r=changed(client,game,**kwargs);r['records'][0]['updated_at']='2026-10-31T00:00:00Z';return r
  with patch('web_sync.collect_game',side_effect=updated),patch('web_sync.time.sleep'):
   result=self.auto.run(force=True,max_pages=1)
  self.assertEqual(result['source_updated'],2);self.assertEqual(self.count('mod_events'),4)
 def test_disable_between_check_and_write(self):
  self.configure('apply')
  def disable(client,game,**kwargs):self.configure('off');return self.source(client,game,**kwargs)
  with patch('web_sync.collect_game',side_effect=disable),patch('web_sync.time.sleep'):
   result=self.auto.run(force=True,max_pages=1)
  self.assertEqual(result['status'],'failed');self.assertEqual(self.count('mods'),0)
 def test_missing_disk_never_creates_database(self):
  missing=self.root/'missing';auto=AutoSync(missing,state_dir=self.root/'device2')
  with self.assertRaises(ValueError):auto.run()
  self.assertFalse(missing.exists())
  with self.assertRaises(FileNotFoundError):validate_root(missing)
 def test_settings_persistent_validated_and_interval(self):
  self.configure('check');self.run_auto()
  fresh=AutoSync(self.root,self.db,self.games,state_dir=self.root/'device');self.assertEqual(fresh.settings()['mode'],'check')
  self.assertEqual(fresh.run()['status'],'not_due')
  for bad in [0,169,True]:
   with self.assertRaises(ValueError):fresh.configure({**DEFAULTS,'interval_hours':bad})
 def test_shared_web_view_sees_headless_results(self):
  browser=WebSync(self.db,self.root,self.games);self.configure('check');self.run_auto()
  self.assertEqual(browser.view()['status'],'waiting');self.assertEqual(browser.view()['report']['inserted'],2)
 def test_manual_preview_not_overwritten(self):
  service=WebSync(self.db,self.root,self.games)
  with patch('web_sync.collect_game',side_effect=self.source):service.check_games(self.games,max_pages=1)
  self.configure('apply');self.assertEqual(self.run_auto()['status'],'manual_preview_pending');self.assertEqual(self.count('mods'),0)
 def test_locator_changes_drive_not_project(self):
  with patch('manage_auto_sync.identity',return_value='same-project'):
   left=locator('E:/codex/Projects/ErYouToolbox');right=locator('F:/codex/Projects/ErYouToolbox')
  self.assertEqual(left,right);self.assertNotIn('E:',left['relative_root'])
 def test_sql_event_failure_atomic(self):
  self.configure('apply');c=connect_database(self.db);c.execute("CREATE TRIGGER reject_event BEFORE INSERT ON mod_events BEGIN SELECT RAISE(ABORT,'failure'); END");c.commit();c.close()
  self.assertEqual(self.run_auto()['status'],'failed');self.assertEqual(self.count('mods'),0);self.assertEqual(self.count('sync_runs'),0)
 def test_registration_is_explicit_no_real_task_calls(self):
  # Query validates subprocess result only; no Windows task is created by this test.
  with patch('manage_auto_sync.subprocess.run') as call:
   call.return_value.returncode=0;call.return_value.stdout='{"registered":false,"enabled":false}'
   result=manage('query',ROOT,state_dir=self.root/'device')
  self.assertFalse(result['registered']);self.assertIn('-Action',call.call_args.args[0]);self.assertIn('query',call.call_args.args[0])
 def test_bootstrap_missing_project_safe_exit(self):
  if os.name!='nt':self.skipTest('Windows only')
  folder=self.root/'bootstrap';folder.mkdir();shutil.copyfile(ROOT/'scripts/auto_sync_bootstrap.ps1',folder/'bootstrap.ps1')
  (folder/'locator.json').write_text(json.dumps({'format':'eryoutoolbox-auto-locator-v1','project_id':'missing','relative_root':'ErYouToolbox-absent-'+self.root.name}),encoding='utf-8')
  ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
  result=subprocess.run([str(ps),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(folder/'bootstrap.ps1')],capture_output=True,timeout=20)
  self.assertNotEqual(result.returncode,0);self.assertTrue((folder/'scheduled.err.log').is_file())
 def test_task_registration_disable_delete_commands_mocked(self):
  (self.root/'scripts').mkdir();(self.root/'src/eryoutoolbox').mkdir(parents=True)
  for file in ['auto_sync_bootstrap.ps1','manage_auto_sync.ps1','auto_sync.py']:
   shutil.copyfile(ROOT/'scripts'/file,self.root/'scripts'/file)
  (self.root/'src/eryoutoolbox/gamebanana.py').write_text('# test only',encoding='utf-8')
  (self.root/'config/games.json').write_text(json.dumps({'games':self.games}),encoding='utf-8')
  with patch('manage_auto_sync.subprocess.run') as call:
   call.return_value.returncode=0;call.return_value.stdout='{"registered":true,"enabled":true,"interval_hours":6}'
   for action in ['register','disable','delete']:
    manage(action,self.root,self.root/'device')
    self.assertIn(action,call.call_args.args[0])
  self.assertEqual(json.loads((self.root/'device/locator.json').read_text())['project_id'],json.loads((self.root/'config/project_identity.json').read_text())['project_id'])
 def test_first_updated_at_does_not_create_source_update(self):
  self.configure('apply')
  def missing(client,game,**kwargs):
   r=self.source(client,game,**kwargs);r['records'][0]['updated_at']=None;return r
  with patch('web_sync.collect_game',side_effect=missing),patch('web_sync.time.sleep'):self.auto.run(force=True,max_pages=1)
  self.assertEqual(self.run_auto()['source_updated'],0);self.assertEqual(self.count('mod_events'),2)
 def test_source_update_preserves_user_fields_and_images(self):
  self.configure('apply');self.run_auto();c=connect_database(self.db)
  c.execute("UPDATE user_states SET is_read=1,is_favorite=1,note='keep'")
  c.execute("UPDATE mods SET preview_urls_json=?,content_rating_status='ADULT'",(json.dumps([{'image_url':'https://example.com/original.jpg','thumbnail_url':'https://example.com/small.jpg','switch_url':'https://example.com/tiny.jpg'}]),))
  c.execute("INSERT INTO author_subscriptions VALUES('gamebanana',7,'Author','2026-01-01T00:00:00Z')");c.commit()
  before=[tuple(r) for r in c.execute('SELECT * FROM user_states')];images=c.execute('SELECT preview_urls_json FROM mods LIMIT 1').fetchone()[0];c.close()
  def updated(client,game,**kwargs):
   r=self.source(client,game,**kwargs);r['collected_at']='2026-11-02T00:00:00Z';r['records'][0]['updated_at']='2026-11-01T00:00:00Z';return r
  with patch('web_sync.collect_game',side_effect=updated),patch('web_sync.time.sleep'):self.auto.run(force=True,max_pages=1)
  c=connect_database(self.db)
  try:
   self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM user_states')])
   self.assertEqual(json.loads(images),json.loads(c.execute('SELECT preview_urls_json FROM mods LIMIT 1').fetchone()[0]))
   self.assertEqual(c.execute('SELECT COUNT(*) FROM author_subscriptions').fetchone()[0],1)
   self.assertEqual(c.execute('SELECT content_rating_status FROM mods LIMIT 1').fetchone()[0],'ADULT')
  finally:c.close()

 def test_discard_and_confirmation_resolve_pending(self):
  service=WebSync(self.db,self.root,self.games)
  with patch('web_sync.collect_game',side_effect=self.source):service.check_games(self.games,max_pages=1)
  self.configure('check');self.assertEqual(self.run_auto()['status'],'manual_preview_pending')
  with self.assertRaises(ValueError):service.start({'action':'discard','game':None,'token':'wrong'})
  service.start({'action':'discard','game':None,'token':service.state['token']})
  self.assertEqual(WebSync(self.db,self.root,self.games).view()['status'],'discarded')
  self.assertEqual(self.auto.status()['last_run']['status'],'preview_resolved')
  self.assertEqual(self.count('mods'),0);self.assertEqual(service.committed(),{})
  self.assertTrue(list(service.path.parent.glob('discarded_*.json')))
  self.assertEqual(self.run_auto()['status'],'waiting');self.assertEqual(self.count('mods'),0)
  current=WebSync(self.db,self.root,self.games);current.apply()
  self.assertIsNone(WebSync(self.db,self.root,self.games).candidate)
  self.assertEqual(WebSync(self.db,self.root,self.games).state['status'],'success')
if __name__=='__main__':unittest.main()

