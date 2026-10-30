import json,sys,tempfile,sqlite3
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eryoutoolbox.author_updates import check,apply_report,baseline
from eryoutoolbox.database import initialize_database
from eryoutoolbox.subscriptions import set_follow

def reply(value,status=200):return httpx.Response(status,json=value,request=httpx.Request('GET','https://gamebanana.com/test'))

class AuthorChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.db=Path(self.temp.name)/'db.sqlite';initialize_database(self.db)
        c=sqlite3.connect(self.db);c.execute("INSERT INTO mods(source,item_type,item_id,author_id,game_id,first_seen_at,last_checked_at) VALUES('gamebanana','Mod',1,7,8552,'now','now')");c.commit();c.close()
        set_follow(self.db,'gamebanana',7,True)
        self.profile={'_idRow':2,'_sName':'sample','_aSubmitter':{'_idRow':7},'_aGame':{'_idRow':8552},'_tsDateAdded':1600000000,'_tsDateUpdated':1700000000}
        self.client=Mock();self.client.get.side_effect=lambda url,params=None:reply([['Mod',2],['Mod',2]]) if 'Core/List' in url else reply(self.profile)
    def tearDown(self):self.temp.cleanup()
    def preview(self,**kwargs):
        with patch('eryoutoolbox.author_updates.time.sleep'):return check(self.db,ROOT,client=self.client,**kwargs)
    def test_core_parameters_dedupe_and_dryrun(self):
        before=self.db.read_bytes();r=self.preview();self.assertEqual(r['requests'],7);self.assertEqual(len(r['authors'][0]['records']),1)
        params=self.client.get.call_args_list[0].kwargs['params'];self.assertEqual(params['userid'],7);self.assertEqual(params['max_age'],2592000);self.assertEqual(params['include_updated'],1)
        self.assertEqual(before,self.db.read_bytes())
    def test_first_baseline_idempotence_and_real_update(self):
        r=self.preview();result=apply_report(self.db,r);self.assertEqual(result[0]['new_publications'],0)
        self.assertEqual(apply_report(self.db,r),[])
        self.profile['_tsDateUpdated']=1800000000
        r=self.preview();result=apply_report(self.db,r);self.assertEqual(result[0]['source_update_events'],1)
        c=sqlite3.connect(self.db);self.assertEqual(c.execute('SELECT COUNT(*) FROM author_subscriptions').fetchone()[0],1);self.assertIsNotNone(baseline(c,7));c.close()
    def test_resume_does_not_request_successful_author(self):
        r=self.preview();self.client.reset_mock();second=self.preview(resume=r);self.assertEqual(self.client.get.call_count,0);self.assertEqual(second['status'],'success')
    def test_timeout_and429_leave_library_untouched(self):
        before=self.db.read_bytes()
        for item in (httpx.ReadTimeout('offline'),reply({},429)):
            self.client.get.side_effect=item if isinstance(item,Exception) else None;self.client.get.return_value=item
            r=self.preview();self.assertEqual(r['status'],'failed');self.assertEqual(r['requests'],1)
        self.assertEqual(self.db.read_bytes(),before)
    def test_game_or_author_mismatch_rejected(self):
        self.profile['_aGame']['_idRow']=999;r=self.preview();self.assertEqual(r['status'],'failed');self.assertEqual(r['authors'][0]['records'],[])
    def test_backup_failure_rolls_back_mods_and_baseline(self):
        r=self.preview();before=self.db.read_bytes()
        with patch('eryoutoolbox.author_updates.verified_backup',side_effect=OSError('backup failed')):
            with self.assertRaises(OSError):apply_report(self.db,r)
        self.assertEqual(self.db.read_bytes(),before)
    def test_empty_core_and_second_page_bounded(self):
        self.client.get.side_effect=lambda url,params=None:reply([])
        r=self.preview(pages=2);self.assertEqual(r['requests'],6);self.assertEqual(r['status'],'success')

if __name__=='__main__':unittest.main()
