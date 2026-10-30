import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eryoutoolbox.database import initialize_database,connect_database
from web_sync import WebSync

class WebSyncTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'test.db';initialize_database(self.db)
  self.game={'game_id':8552,'name':'Genshin Impact'};self.service=WebSync(self.db,self.root,[self.game])
 def tearDown(self):self.tmp.cleanup()
 def sample(self,updated='2026-10-01T00:00:00Z'):
  return {'collected_at':'2026-10-30T00:00:00Z','records':[{'source':'gamebanana','item_type':'Mod','item_id':123,'game_id':8552,'title':'Test','updated_at':updated}], 'failure_reasons':[],'actual_record_count':1,'request_count':1}
 def check(self,result=None):
  with patch('web_sync.collect_game',return_value=result or self.sample()),patch('web_sync.time.sleep'):self.service.check(self.game)
 def count(self,table):
  c=connect_database(self.db)
  try:return c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
  finally:c.close()
 def test_preview_and_restart_persistence(self):
  self.check();self.assertEqual(self.count('mods'),0);self.assertFalse((self.root/'backups').exists())
  self.service.apply();self.assertEqual(self.count('mods'),1);self.assertEqual(self.count('mod_events'),1)
  self.service=WebSync(self.db,self.root,[self.game]);self.check();self.service.apply();self.assertEqual(self.count('mods'),1);self.assertEqual(self.count('mod_events'),1)
 def test_real_update_evidence(self):
  self.check();self.service.apply();sample=self.sample('2026-10-29T00:00:00Z');sample['collected_at']='2026-10-31T00:00:00Z';self.check(sample);self.assertEqual(self.service.state['report']['source_update_events'],1)
 def test_conflict(self):
  self.check();c=connect_database(self.db);c.execute("INSERT INTO mods(source,item_type,item_id,first_seen_at,last_checked_at) VALUES('x','Mod',9,'x','x')");c.commit();c.close()
  with self.assertRaises(ValueError):self.service.apply()
  self.assertEqual(self.count('mods'),1)
 def test_backup_failure_rollback(self):
  self.check()
  with patch('web_sync.backup_database',side_effect=OSError('backup failed')):
   with self.assertRaises(OSError):self.service.apply()
  self.assertEqual(self.count('mods'),0);self.assertEqual(self.count('mod_events'),0)
 def test_sql_failure_rollback(self):
  self.check();c=connect_database(self.db);c.execute("CREATE TRIGGER reject_event BEFORE INSERT ON mod_events BEGIN SELECT RAISE(ABORT,'fail'); END");c.commit();c.close()
  with self.assertRaises(Exception):self.service.apply()
  self.assertEqual(self.count('mods'),0)
 def test_timeout_and_rate_limit(self):
  for reason in ['ReadTimeout','HTTP 429 Retry-After 10']:
   sample=self.sample();sample.update(records=[],actual_record_count=0,failure_reasons=[{'reason':reason}]);self.check(sample);self.assertEqual(self.service.state['status'],'failed');self.assertEqual(self.count('mods'),0)
 def test_http_preview_confirm_and_status_recovery(self):
  import threading,time,json,httpx
  from http.server import ThreadingHTTPServer
  from react_api import ReadOnlyAPI,make_handler
  api=ReadOnlyAPI(self.db);server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(api,0));port=server.server_port
  server.RequestHandlerClass=make_handler(api,port)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  headers={'Origin':'http://127.0.0.1:5173','X-ErYouToolbox':'1'}
  try:
   with patch('web_sync.collect_game',return_value=self.sample()),httpx.Client(base_url=f'http://127.0.0.1:{port}',headers=headers) as client:
    self.assertEqual(client.post('/api/sync',json={'action':'check','game':8552}).status_code,200)
    def wait():
     for _ in range(200):
      state=client.get('/api/sync').json()
      if state['status'] not in ('checking','importing'):return state
      time.sleep(.01)
     self.fail('Task did not finish')
    state=wait();self.assertEqual(state['status'],'waiting');self.assertEqual(self.count('mods'),0)
    self.assertEqual(client.post('/api/sync',json={'action':'confirm','game':8552,'token':state['token']}).status_code,200)
    self.assertEqual(wait()['status'],'success');self.assertEqual(self.count('mods'),1)
    # A new client can recover status after the original page closes.
    with httpx.Client() as reopened:self.assertEqual(reopened.get(f'http://127.0.0.1:{port}/api/sync').json()['status'],'success')
  finally:server.shutdown();server.server_close();thread.join()
 def test_busy_identity_expiry(self):
  self.service.state={'status':'checking'}
  with self.assertRaises(ValueError):self.service.start({'action':'check','game':8552})
  self.check()
  with self.assertRaises(ValueError):self.service.start({'action':'confirm','game':8552,'token':'bad'})
  self.service.candidate['created']=0
  with self.assertRaises(ValueError):self.service.start({'action':'confirm','game':8552,'token':self.service.state['token']})
class MultiGameWebSyncTests(unittest.TestCase):
 tearDown=WebSyncTests.tearDown
 sample=WebSyncTests.sample
 count=WebSyncTests.count
 def setUp(self):
  WebSyncTests.setUp(self)
  import json
  self.games=json.loads((ROOT/'config/games.json').read_text(encoding='utf-8'))['games']
  self.service=WebSync(self.db,self.root,self.games)
 def run_games(self,fail=None,limit=None):
  self.calls=[]
  def collect(client,game,**kwargs):
   self.calls.append(game['game_id'])
   self.assertEqual(kwargs['max_pages'],1);self.assertEqual(kwargs['per_page'],10)
   sample=self.sample();sample['records'][0].update(item_id=game['game_id'],game_id=game['game_id'])
   if game['game_id']==fail:
    sample.update(records=[],actual_record_count=0,failure_reasons=[{'http_status':limit or 500,'reason':'failure'}])
   return sample
  with patch('web_sync.collect_game',side_effect=collect),patch('web_sync.time.sleep'):
   self.service.check_games(self.games if limit!=2 else self.games[:2],max_pages=1)
 def test_two_games_in_order(self):
  self.run_games(limit=2);self.assertEqual(self.calls,[g['game_id'] for g in self.games[:2]]);self.assertEqual(self.service.state['report']['inserted'],2);self.assertEqual(self.count('mods'),0)
 def test_six_confirm_idempotent_persistent(self):
  self.run_games();self.assertEqual(self.calls,[g['game_id'] for g in self.games]);self.assertEqual(self.service.state['requests'],6)
  self.assertEqual(self.service.state['report']['inserted'],6);self.service.apply();self.assertEqual(self.count('mods'),6)
  self.service=WebSync(self.db,self.root,self.games);self.run_games();self.service.apply();self.assertEqual(self.count('mods'),6);self.assertEqual(self.count('mod_events'),6)
 def test_failed_game_isolated(self):
  self.run_games(fail=self.games[1]['game_id']);self.assertEqual(len(self.calls),6);self.service.apply();self.assertEqual(self.count('mods'),5);self.assertEqual(self.service.state['status'],'partial')
 def test_rate_limit_stops_preserves(self):
  self.run_games(fail=self.games[1]['game_id'],limit=429);self.assertEqual(len(self.calls),2)
  self.assertEqual([s['status'] for s in self.service.state['games']],['success','failed','skipped','skipped','skipped','skipped'])
  self.service.apply();self.assertEqual(self.count('mods'),1);self.assertEqual(self.service.state['status'],'partial')
 def test_mismatched_identity_is_excluded(self):
  with patch('web_sync.collect_game',return_value=self.sample()),patch('web_sync.time.sleep'):
   self.service.check_games(self.games)
  self.assertEqual(self.service.state['report']['inserted'],1)
 def test_all_request_and_busy(self):
  import threading
  entered=threading.Event();release=threading.Event()
  def hold(*args):entered.set();release.wait(3)
  with patch.object(self.service,'check_games',side_effect=hold):
   self.service.start({'action':'check_all'});self.assertTrue(entered.wait(2))
   with self.assertRaises(ValueError):self.service.start({'action':'check_all'})
   release.set()

if __name__=='__main__':unittest.main()
