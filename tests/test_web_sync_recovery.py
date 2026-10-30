"""File database recovery tests; no production data or live API."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_web_sync as helpers
from web_sync import WebSync, page_plan
from eryoutoolbox.database import connect_database

class RecoveryTests(unittest.TestCase):
 setUp=helpers.WebSyncTests.setUp
 tearDown=helpers.WebSyncTests.tearDown
 count=helpers.WebSyncTests.count
 def scan(self,pages=None,*,resume=False,fail=None,stop=None,budget=3,games=None):
  self.calls=[]
  def collect(client,game,**kwargs):
   page=kwargs['start_page'];self.calls.append((game['game_id'],page))
   if fail and page==fail[0]:
    return {'records':[],'actual_record_count':0,'failure_reasons':[{'page':page,'http_status':fail[1],'reason':'HTTP 429' if fail[1]==429 else 'ReadTimeout'}],'collected_at':'2026-10-30T00:00:00Z','request_count':2 if fail[1]!=429 else 1}
   ids=(pages or {}).get(page,[game['game_id']*100+page])
   records=[{'source':'gamebanana','item_type':'Mod','item_id':i,'game_id':game['game_id'],'title':f'Mod {i}',
     'updated_at':None,'created_at':'2020-01-01T00:00:00Z' if i%2 else '2026-10-29T00:00:00Z'} for i in ids]
   if stop==page:self.service.cancel.set()
   return {'records':records,'actual_record_count':len(records),'failure_reasons':[],
     'collected_at':'2026-10-30T00:00:00Z','request_count':1}
  with patch('web_sync.collect_game',side_effect=collect),patch('web_sync.time.sleep'):
   self.service.check_games(games or [self.game],10,budget,resume)
 def assert_balanced(self):
  stats=self.service.view()['statistics']
  self.assertEqual(stats['fetched'],stats['classified']+stats['duplicates']+stats['unclassified'])
 def test_three_pages_mixed_age_no_early_stop(self):
  self.scan({1:[1],2:[2],3:[3]});self.assertEqual(len(self.calls),3)
  self.assertEqual(self.service.state['report']['inserted'],3);self.assert_balanced()
  self.assertEqual(self.service.state['coverage'],'incomplete');self.assertEqual(self.service.committed(),{})
 def test_duplicates_and_missing_evidence(self):
  self.scan({1:[1,2],2:[2,3],3:[1,3]});self.assertEqual(self.service.state['statistics']['duplicates'],3)
  self.assertEqual(self.service.state['report']['inserted'],3);self.assert_balanced()
 def test_partial_then_resume_with_overlap(self):
  self.scan(fail=(3,None));self.assertEqual(self.service.state['games'][0]['pages'],[1,2]);self.assert_balanced()
  self.service.apply();self.assertEqual(self.service.committed()['8552']['frontier'],2)
  self.service=WebSync(self.db,self.root,[self.game]);self.scan(resume=True)
  self.assertEqual([p for _,p in self.calls],[1,2,3]);self.service.apply();self.assertEqual(self.count('mods'),3)
 def test_rate_limit_stops_other_games(self):
  games=[self.game,{'game_id':9,'name':'Other'}];self.scan(fail=(2,429),games=games)
  self.assertEqual(len(self.calls),2);self.assertEqual(self.service.state['scan_status'],'rate_limited')
  self.service.apply();self.assertEqual(self.count('mods'),1);self.assertNotIn('9',self.service.committed())
 def test_cancel_uncommitted_progress_rechecks(self):
  self.scan(stop=2);self.assertEqual(len(self.calls),2);self.assertEqual(self.service.committed(),{})
  self.service=WebSync(self.db,self.root,[self.game]);self.assertEqual(self.service.state['status'],'waiting')
  self.scan(resume=True);self.assertEqual([p for _,p in self.calls],[1,2,3])
 def test_page_drift_head_and_overlap(self):
  self.scan({1:[1],2:[2],3:[3]});self.service.apply()
  self.service=WebSync(self.db,self.root,[self.game]);self.scan({1:[99],3:[2,3],4:[4]},resume=True)
  self.assertEqual([p for _,p in self.calls],[1,3,4]);self.service.apply()
  self.assertEqual(self.count('mods'),5);self.assertEqual(self.service.state['coverage'],'incomplete')
 def test_restart_preview_and_idempotency(self):
  self.scan();self.service=WebSync(self.db,self.root,[self.game]);self.service.apply()
  events=self.count('mod_events');self.scan();self.service.apply();self.assertEqual(self.count('mod_events'),events)
 def test_rollback_does_not_advance(self):
  self.scan()
  with patch('web_sync.backup_database',side_effect=OSError('failed')):
   with self.assertRaises(OSError):self.service.apply()
  self.assertEqual(self.service.committed(),{});self.assertEqual(self.count('mods'),0)
 def test_checkpoint_survives_journal_failure(self):
  self.scan()
  with patch.object(self.service,'save',side_effect=OSError('disk full')):self.service.apply()
  self.service=WebSync(self.db,self.root,[self.game]);self.assertEqual(self.service.state['status'],'success')
  self.assertEqual(self.service.committed()['8552']['frontier'],3)
 def test_review_and_images_preserved(self):
  self.scan();self.service.apply();c=connect_database(self.db)
  c.execute("UPDATE user_states SET is_read=1,note='keep'")
  c.execute("UPDATE mods SET preview_urls_json=?,content_rating_status='ADULT'",(json.dumps([{'image_url':'https://example.com/full.jpg','thumbnail_url':'https://example.com/small.jpg','switch_url':'https://example.com/tiny.jpg'}]),))
  c.execute("INSERT INTO author_subscriptions VALUES('gamebanana',7,'Author','2026-10-01T00:00:00Z')");c.commit()
  before=[tuple(r) for r in c.execute('SELECT * FROM user_states')];image=c.execute('SELECT preview_urls_json FROM mods LIMIT 1').fetchone()[0];c.close()
  self.scan();self.service.apply();c=connect_database(self.db)
  self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM user_states')]);self.assertEqual(image,c.execute('SELECT preview_urls_json FROM mods LIMIT 1').fetchone()[0])
  self.assertEqual(c.execute('SELECT COUNT(*) FROM author_subscriptions').fetchone()[0],1);c.close()
 def test_new_check_does_not_regress_frontier(self):
  self.scan();self.service.apply();self.scan(resume=True);self.service.apply();self.assertEqual(self.service.committed()['8552']['frontier'],4)
  self.scan();self.service.apply();self.assertEqual(self.service.committed()['8552']['frontier'],4)
 def test_bounded_config(self):
  for n in [0,11,True]:
   with self.assertRaises(ValueError):self.service.start({'action':'check','game':8552,'max_pages':n})
  self.assertEqual(page_plan(4,3),[1,4,5])
 def test_collector_start_page_and_retry_budget(self):
  import httpx
  from eryoutoolbox.gamebanana import collect_game
  calls=[]
  def transport(request):
   calls.append(int(request.url.params['_nPage']))
   if len(calls)==1:raise httpx.ReadTimeout('simulated',request=request)
   return httpx.Response(200,json={'_aRecords':[{'_idRow':7,'_aGame':{'_idRow':8552}}],'_aMetadata':{}})
  with httpx.Client(transport=httpx.MockTransport(transport)) as client,patch('eryoutoolbox.gamebanana.time.sleep'):
   result=collect_game(client,self.game,start_page=4,max_pages=1)
  self.assertEqual(calls,[4,4]);self.assertEqual(result['request_count'],2)
  self.assertEqual(result['records'][0]['item_id'],7)
 def test_collector_429_retry_after(self):
  import httpx
  from eryoutoolbox.gamebanana import collect_game
  with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(429,headers={'Retry-After':'2'}))) as client,patch('eryoutoolbox.gamebanana.time.sleep') as sleep:
   result=collect_game(client,self.game,max_pages=3)
  self.assertEqual(result['request_count'],1);sleep.assert_called_once_with(2)
 def test_metadata_only_category_closes_statistics_gap(self):
  from web_sync import classify
  report={'inserted':43,'source_update_events':2,'updated':3,'unchanged':14,'skipped':0,'unique_records':60,'batch_duplicates':0,'input_records':60}
  result=classify(report,60)
  self.assertEqual(result['metadata_only'],1);self.assertEqual(result['classified'],60)
 def test_six_games_three_pages_isolated(self):
  games=json.loads((helpers.ROOT/'config/games.json').read_text(encoding='utf-8'))['games']
  self.scan(games=games);self.assertEqual(len(self.calls),18);self.service.apply()
  self.assertEqual(self.count('mods'),18);self.assertEqual(len(self.service.committed()),6)
 def test_interrupted_api_restarts_from_committed_overlap(self):
  self.scan(fail=(3,None));self.service.apply()
  self.service.state['status']='checking';self.service.save()
  self.service=WebSync(self.db,self.root,[self.game])
  # Same task already committed: transaction evidence wins over an interrupted journal.
  self.assertEqual(self.service.state['status'],'partial')
  self.scan(resume=True);self.assertEqual([p for _,p in self.calls],[1,2,3])
 def test_portable_preview_relocation(self):
  import shutil
  from eryoutoolbox.database import backup_database
  self.scan()
  with tempfile.TemporaryDirectory(dir=self.root) as folder:
   moved=Path(folder);backup_database(self.db,moved/'test.db')
   path=moved/'logs/web_sync/task.json';path.parent.mkdir(parents=True)
   shutil.copyfile(self.service.path,path)
   other=WebSync(moved/'test.db',moved,[self.game]);self.assertEqual(other.state['status'],'waiting')
   other.apply();self.assertEqual(other.committed()['8552']['frontier'],3)
if __name__=='__main__':unittest.main()
