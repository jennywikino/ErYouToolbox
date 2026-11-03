"""rc3 lifecycle and cache safety, isolated files/SQLite and mocked HTTP only."""
from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import subprocess
import os
import base64
import unittest
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eryoutoolbox.cache_management import CacheManagement,safe_child
from eryoutoolbox.database import initialize_database
from eryoutoolbox.popular import PopularClient
from eryoutoolbox.source_detail import SourceDetail,summary
from eryoutoolbox.models import normalize_record
from backfill_content_ratings import instance_lock
from react_api import ReadOnlyAPI
from web_sync import recent_window,WebSync
from auto_sync import AutoSync,DEFAULTS


class CleanupTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=self.root/'data/eryoutoolbox.db';initialize_database(self.db)
  self.cache=CacheManagement(self.root,PopularClient(),SourceDetail())
 def tearDown(self):self.temp.cleanup()
 def avatar(self,aid=1,expires=1):
  p=self.root/f'logs/author_profiles/{aid}.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'author_id':aid,'expires':expires}));return p
 def preview(self,*ids):return self.cache.command({'action':'preview','categories':list(ids)})
 def test_inventory_and_preview_no_change(self):
  p=self.avatar();before=self.db.read_bytes();plan=self.preview('avatars')
  self.assertEqual(plan['files'],['logs/author_profiles/1.json']);self.assertTrue(p.exists())
  cat=next(c for c in self.cache.status()['categories'] if c['id']=='avatars');self.assertEqual(cat['files'],1);self.assertGreater(cat['bytes'],0)
  self.assertEqual(before,self.db.read_bytes())
 def test_clear_only_expired_recognized_files_preserves_data(self):
  expired=self.avatar();fresh=self.avatar(2,10**12);bad=self.root/'logs/author_profiles/3.json';bad.write_text('invalid')
  protected=[self.root/'data/backups/old.db',self.root/'logs/history_sync/state.json',self.root/'logs/auto_sync/settings.json',self.root/'logs/content_ratings/checkpoint_all.json']
  for p in protected:p.parent.mkdir(parents=True,exist_ok=True);p.write_text('keep')
  with closing(sqlite3.connect(self.db)) as c,c:
   c.execute("INSERT INTO mods(source,item_type,item_id,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',1,'x','x')")
   c.execute("INSERT INTO user_states(source,item_type,item_id,is_read,note,updated_at) VALUES('gamebanana','Mod',1,1,'keep','x')")
   c.execute("INSERT INTO author_subscriptions VALUES('gamebanana',7,'A','x')")
  before=self.db.read_bytes();plan=self.preview('avatars');result=self.cache.command({'action':'clear','token':plan['token']})
  self.assertEqual(result['status'],'success');self.assertFalse(expired.exists());self.assertTrue(fresh.exists());self.assertTrue(bad.exists())
  self.assertTrue(all(p.read_text()=='keep' for p in protected));self.assertEqual(self.db.read_bytes(),before)
 def test_busy_and_shared_lock_conflict(self):
  p=self.avatar();plan=self.preview('avatars');self.cache.busy=lambda:True
  with self.assertRaises(ValueError):self.cache.command({'action':'clear','token':plan['token']})
  self.cache.busy=lambda:False
  with instance_lock(self.root/'logs/content_ratings/instance.lock'):
   with self.assertRaises(RuntimeError):self.cache.command({'action':'clear','token':plan['token']})
  self.assertTrue(p.exists())
 def test_changed_or_expired_preview_rejected(self):
  p=self.avatar();plan=self.preview('avatars');p.write_text('changed')
  with self.assertRaises(ValueError):self.cache.command({'action':'clear','token':plan['token']})
  self.avatar();plan=self.preview('avatars')
  with patch('eryoutoolbox.cache_management.time.time',return_value=10**12):
   with self.assertRaises(ValueError):self.cache.command({'action':'clear','token':plan['token']})
 def test_locked_file_fails_safely_without_force(self):
  if sys.platform!='win32':self.skipTest('Windows file sharing')
  p=self.avatar();plan=self.preview('avatars')
  with p.open('rb'):
   result=self.cache.command({'action':'clear','token':plan['token']})
  self.assertEqual(result['status'],'partial');self.assertTrue(p.exists())
 def test_paths_and_unknown_categories_rejected(self):
  for path in (self.root,self.root.parent,self.root/'../escape'):
   with self.assertRaises(ValueError):safe_child(self.root,path)
  for category in ('data','backups','logs','smoke','../../','checkpoints'):
   with self.assertRaises(ValueError):self.preview(category)
 def test_links_are_not_followed(self):
  folder=self.root/'logs';folder.mkdir()
  target=self.root/'external';target.mkdir()
  link=folder/'author_profiles'
  try:link.symlink_to(target,target_is_directory=True)
  except OSError:
   if os.name!='nt':raise
   command="New-Item -ItemType Junction -Path '"+str(link).replace("'","''")+"' -Target '"+str(target).replace("'","''")+"' | Out-Null"
   ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
   subprocess.run([str(ps),'-NoProfile','-EncodedCommand',base64.b64encode(command.encode('utf-16le')).decode('ascii')],check=True,capture_output=True)
  with self.assertRaises(ValueError):self.cache.entries()
 def test_memory_cooldown_and_webview_callback(self):
  self.cache.popular.cache['x']=(1,{});self.cache.popular.pause_until=999
  self.cache.webview_clear=Mock();plan=self.preview('memory','webview');self.cache.command({'action':'clear','token':plan['token']})
  self.assertFalse(self.cache.popular.cache);self.assertEqual(self.cache.popular.pause_until,999);self.cache.webview_clear.assert_called_once()
 def test_unavailable_or_failed_webview_never_removes_profile(self):
  with self.assertRaises(ValueError):self.preview('webview')
  file=self.root/'cache/webview/Default/Preferences';file.parent.mkdir(parents=True);file.write_text('keep')
  self.cache.webview_clear=Mock(side_effect=RuntimeError('unavailable'));plan=self.preview('webview')
  self.assertEqual(self.cache.command({'action':'clear','token':plan['token']})['status'],'partial');self.assertEqual(file.read_text(),'keep')
 def test_retired_rating_api_does_not_load_missing_config(self):
  resources=self.root/'bundle';(resources/'config').mkdir(parents=True);(resources/'config/games.json').write_bytes((ROOT/'config/games.json').read_bytes())
  api=ReadOnlyAPI(self.db,runtime_root=self.root,resources_root=resources)
  self.assertEqual(api.get('/api/rating-enrichment')[0],410);self.assertEqual(api.get('/api/content-ratings')[0],410)
 def test_window_uses_source_release_or_update_not_modified(self):
  captured='2026-11-03T00:00:00Z'
  for r,expected in [({'created_at':'2026-11-02T00:00:00Z'},'in_window'),({'created_at':'2025-01-01T00:00:00Z','updated_at':'2026-10-31T00:00:00Z'},'in_window'),({'created_at':'2025-01-01T00:00:00Z','modified_at':captured},'out_of_window'),({'modified_at':captured},'missing_dates'),({'updated_at':'invalid'},'missing_dates'),({'created_at':'2028-01-01T00:00:00Z'},'out_of_window')]:
   self.assertEqual(recent_window(r,captured),expected)
 def test_window_preview_counts_and_apply_idempotence(self):
  game={'game_id':8552,'name':'G'};service=WebSync(self.db,self.root,[game])
  rows=[{'source':'gamebanana','item_type':'Mod','item_id':i,'game_id':8552,**dates} for i,dates in [(1,{'created_at':'2026-10-01T00:00:00Z'}),(2,{'created_at':'2025-01-01T00:00:00Z','updated_at':'2026-10-20T00:00:00Z'}),(3,{'created_at':'2025-01-01T00:00:00Z'}),(4,{})]]
  result={'records':rows,'request_count':1,'actual_record_count':4,'collected_at':'2026-11-03T00:00:00Z','failure_reasons':[]}
  before=self.db.read_bytes()
  with patch('web_sync.collect_game',return_value=result):service.check_games([game],10,1,window_days=90)
  self.assertEqual(self.db.read_bytes(),before);self.assertEqual(service.state['statistics']['classified'],4);self.assertEqual(service.state['statistics']['unclassified'],0)
  self.assertEqual(service.state['statistics']['out_of_window'],1);self.assertEqual(service.state['statistics']['missing_dates'],1)
  self.assertEqual(service.state['coverage'],'incomplete');service.apply();self.assertTrue(list((self.db.parent/'backups').glob('*.db')))
  with patch('web_sync.collect_game',return_value=result):service.check_games([game],10,1,window_days=90)
  service.apply();self.assertEqual(service.state['report']['inserted'],0)
  with closing(sqlite3.connect(self.db)) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM mods').fetchone()[0],2)
 def test_metrics_only_true_source_numbers_and_saved_roundtrip(self):
  r=normalize_record({'_idRow':1,'_nLikeCount':0,'_nViewCount':123,'_nDownloadCount':None,'_nPostCount':True},{'game_id':8552})
  self.assertEqual(r['metrics'],{'likes':0,'views':123});self.assertEqual(summary(r)['metrics'],r['metrics'])
 def test_long_retry_after_blocks_manual_and_automatic_refresh(self):
  import time
  game={'game_id':8552,'name':'G'};service=WebSync(self.db,self.root,[game]);before=time.time()
  result={'records':[],'request_count':1,'actual_record_count':0,'collected_at':'2026-11-03T00:00:00Z','failure_reasons':[{'http_status':429,'retry_after_seconds':86400,'reason':'rate limited'}]}
  with patch('web_sync.collect_game',return_value=result):service.check_games([game],10,1,window_days=90)
  cooldown=json.loads((self.root/'logs/history_sync/cooldown.json').read_text())
  self.assertGreaterEqual(cooldown['not_before'],before+86400)
  with self.assertRaisesRegex(ValueError,'cooldown'):service.start({'action':'check','game':8552})
  auto=AutoSync(self.root,self.db,[game],state_dir=self.root/'device');auto.configure({**DEFAULTS,'mode':'apply'})
  with patch('web_sync.collect_game') as call:
   self.assertEqual(auto.run(force=True)['status'],'cooldown');call.assert_not_called()
 def test_queued_history_job_is_visible_before_it_takes_the_source_lock(self):
  api=ReadOnlyAPI(self.db,runtime_root=self.root)
  api.history_sync.running.acquire()
  try:
   self.assertTrue(api.history_sync.running.locked())
   with self.assertRaisesRegex(ValueError,'active'):api.cache.command({'action':'preview','categories':['memory']})
   self.assertEqual(api.history_sync.launch(manual=True)['status'],'already_running')
  finally:api.history_sync.running.release()

if __name__=='__main__':unittest.main()
