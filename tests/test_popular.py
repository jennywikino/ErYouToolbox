from pathlib import Path
import sys,tempfile,sqlite3,json
import unittest
from unittest.mock import Mock,patch
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from eryoutoolbox.popular import PopularClient,SORTS,link_local
from eryoutoolbox.database import initialize_database

GAME={'game_id':8552,'name':'Genshin Impact'}
def row(i=1):return {'_idRow':i,'_sModelName':'Mod','_sName':'Test','_aGame':{'_idRow':8552},'_aSubmitter':{'_idRow':7,'_sName':'Author'},'_bHasContentRatings':False,'_nLikeCount':123,'_aPreviewMedia':{'_aImages':[{'_sBaseUrl':'https://images.gamebanana.com/img/ss/mods','_sFile':'original.jpg','_sFile530':'530-90_original.jpg'}]}}
def response(rows,status=200):return httpx.Response(status,json={'_aRecords':rows,'_aMetadata':{'_nPerpage':2,'_nRecordCount':4}},request=httpx.Request('GET','https://gamebanana.com/test'))

class PopularTests(unittest.TestCase):
    def setUp(self):
        self.client=Mock();self.client.get.return_value=response([row(1),row(2)])
        self.clock=Mock(return_value=10000)
        self.api=PopularClient(self.client,self.clock)
        self.sleep=patch('eryoutoolbox.popular.time.sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
    def test_three_sorts_and_parameters(self):
        for sort,alias in SORTS.items():
            self.api.fetch(GAME,sort,limit=2)
            params=self.client.get.call_args.kwargs['params']
            self.assertEqual(params['_sSort'],alias);self.assertEqual(params['_aFilters[Generic_Game]'],8552)
    def test_page_positions_and_missing_metrics_and_unknown(self):
        data=self.api.fetch(GAME,page=2,limit=2)
        self.assertEqual([i['rank'] for i in data['items']],[3,4])
        self.assertEqual(data['items'][0]['metrics'],{'likes':123})
        self.assertEqual(data['items'][0]['source_ratings']['codes'],['-'])
    def test_images_use_existing_normalizer(self):
        image=self.api.fetch(GAME,limit=2)['items'][0]['preview_images'][0]
        self.assertTrue(image['image_url'].endswith('/original.jpg'));self.assertTrue(image['thumbnail_url'].endswith('/530-90_original.jpg'))
    def test_cache_refresh_and_expiry(self):
        self.api.fetch(GAME,limit=2);self.assertTrue(self.api.fetch(GAME,limit=2)['cached']);self.assertEqual(self.client.get.call_count,1)
        self.api.fetch(GAME,limit=2,refresh=True);self.assertEqual(self.client.get.call_count,2)
        self.clock.return_value+=1801;self.api.fetch(GAME,limit=2);self.assertEqual(self.client.get.call_count,3)
    def test_wrong_game_or_structure_not_cached(self):
        bad=row();bad['_aGame']['_idRow']=19567;self.client.get.return_value=response([bad,row(2)])
        with self.assertRaises(RuntimeError):self.api.fetch(GAME,limit=2)
        self.assertEqual(self.api.cache,{})
    def test_429_cooldown_stops_refresh(self):
        self.client.get.return_value=httpx.Response(429,headers={'Retry-After':'60'},request=httpx.Request('GET','https://gamebanana.com/test'))
        with self.assertRaises(RuntimeError):self.api.fetch(GAME,limit=2)
        with self.assertRaises(RuntimeError):self.api.fetch(GAME,limit=2,refresh=True)
        self.assertEqual(self.client.get.call_count,1)
    def test_timeout_and_invalid_json(self):
        self.client.get.side_effect=httpx.ReadTimeout('offline')
        with self.assertRaises(httpx.ReadTimeout):self.api.fetch(GAME,limit=2)
        self.client.get.side_effect=None;self.client.get.return_value=httpx.Response(200,content=b'<html>',request=httpx.Request('GET','https://gamebanana.com/test'))
        with self.assertRaises(RuntimeError):self.api.fetch(GAME,limit=2)
    def test_limit_rejected_before_request(self):
        for limit in (0,21):
            with self.assertRaises(ValueError):self.api.fetch(GAME,limit=limit)
        self.assertEqual(self.client.get.call_count,0)
    def test_local_link_by_full_identity_and_database_unchanged(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            db=Path(directory)/'test.db';initialize_database(db);c=sqlite3.connect(db)
            for source,i in [('gamebanana',1),('other',2)]:c.execute('INSERT INTO mods(source,item_type,item_id,first_seen_at,last_checked_at) VALUES(?,?,?,?,?)',(source,'Mod',i,'now','now'))
            c.commit();c.close();before=db.read_bytes()
            data=link_local(db,self.api.fetch(GAME,limit=2))
            self.assertEqual([i['is_local'] for i in data['items']],[True,False]);self.assertEqual(db.read_bytes(),before)

if __name__=='__main__':unittest.main()
