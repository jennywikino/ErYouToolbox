import sys
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from eryoutoolbox.popular import PopularClient
from tests.test_popular import row,response,GAME
NOW=2000000000
def item(i,age,likes=1,views=2):
    r=row(i);r.update(_tsDateAdded=NOW-age*86400,_nLikeCount=likes,_nViewCount=views);return r

class RecentTests(unittest.TestCase):
    def setUp(self):
        self.client=Mock();self.api=PopularClient(self.client,Mock(return_value=10000))
        self.sleep=patch('eryoutoolbox.popular.time.sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
    def recent(self,**kwargs):return self.api.recent(GAME,per_page=2,now=NOW,**kwargs)
    def test_windows_boundary_and_creation_only(self):
        for days in (7,30,90):
            self.api.recent_cache.clear()
            self.client.get.return_value=response([item(1,days),item(2,days+1)])
            r=self.recent(days=days,max_pages=1,refresh=True)
            self.assertEqual(r['candidate_count'],1);self.assertEqual(r['coverage'],'boundary_observed')
            self.assertEqual(self.client.get.call_args.kwargs['params']['_sSort'],'Generic_Newest')
    def test_paging_reaches_cap_incomplete_and_sorts_then_paginates(self):
        self.client.get.side_effect=[response([item(1,1,1),item(2,2,20)]),response([item(3,3,9),item(4,4,2)])]
        r=self.recent(max_pages=2,limit=1)
        self.assertEqual(r['items'][0]['item_id'],2);self.assertEqual(r['coverage'],'incomplete')
        second=self.recent(max_pages=2,limit=1,page=2)
        self.assertEqual(second['items'][0]['item_id'],3);self.assertEqual(self.client.get.call_count,2)
    def test_sort_switch_reuses_candidates_and_downloads_never_use_views(self):
        self.client.get.return_value=response([item(1,1,5,1),item(2,2,1,10)])
        self.assertEqual(self.recent(max_pages=1)['items'][0]['item_id'],1)
        self.assertEqual(self.recent(max_pages=1,sort='views')['items'][0]['item_id'],2)
        self.assertEqual(self.recent(max_pages=1,sort='downloads')['items'],[])
        self.assertEqual(self.client.get.call_count,1)
    def test_duplicates_dedup_and_do_not_claim_boundary(self):
        self.client.get.side_effect=[response([item(1,1),item(2,2)]),response([item(2,2),item(3,40)])]
        r=self.recent();self.assertEqual(r['candidate_count'],2);self.assertEqual(r['duplicates'],1);self.assertEqual(r['coverage'],'incomplete')
    def test_missing_and_out_of_order_times_prevent_boundary_claim(self):
        for rows in ([row(1),item(2,40)],[item(1,40),item(2,1)]):
            self.client.get.return_value=response(rows)
            r=self.recent(max_pages=1,refresh=True)
            self.assertEqual(r['coverage'],'incomplete')
    def test_modified_recent_does_not_admit_old_creation(self):
        old=item(1,60);old['_tsDateModified']=NOW;self.client.get.return_value=response([old,item(2,61)])
        self.assertEqual(self.recent(max_pages=1)['candidate_count'],0)
    def test_failed_second_page_keeps_partial_and_first_failure_raises(self):
        self.client.get.side_effect=[response([item(1,1),item(2,2)]),httpx.ReadTimeout('offline')]
        r=self.recent();self.assertEqual(r['status'],'partial');self.assertEqual(r['coverage'],'incomplete');self.assertTrue(r['errors'])
        self.client.get.side_effect=httpx.ReadTimeout('offline')
        with self.assertRaises(RuntimeError):self.recent(refresh=True)
    def test_refresh_reloads_and_limits_reject(self):
        self.client.get.return_value=response([item(1,1),item(2,2)])
        self.recent(max_pages=1);self.recent(max_pages=1);self.assertEqual(self.client.get.call_count,1)
        self.recent(max_pages=1,refresh=True);self.assertEqual(self.client.get.call_count,2)
        for kwargs in ({'days':8},{'max_pages':6},{'per_page':51}):
            with self.assertRaises(ValueError):self.api.recent(GAME,**kwargs)
    def test_missing_likes_are_excluded_without_inventing_zero(self):
        missing=item(1,1);missing.pop('_nLikeCount');self.client.get.return_value=response([missing,item(2,2)])
        r=self.recent(max_pages=1);self.assertEqual(r['missing_metrics'],1);self.assertEqual(len(r['items']),1)

if __name__=='__main__':unittest.main()
