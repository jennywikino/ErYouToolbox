from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eryoutoolbox.gamebanana import collect_game, deduplicate  # noqa: E402
from eryoutoolbox.models import normalize_record  # noqa: E402


GAME = {"name": "Genshin Impact", "game_id": 8552}


def record(**updates):
    value = {
        "_idRow": 101, "_sModelName": "Mod", "_sName": "Sample",
        "_sProfileUrl": "https://gamebanana.com/mods/101",
        "_tsDateAdded": 1700000000, "_tsDateModified": 1700000001,
        "_sVersion": "1.0", "_aSubmitter": {"_idRow": 7, "_sName": "Author", "_sProfileUrl": "https://gamebanana.com/members/7"},
        "_aGame": {"_idRow": 8552}, "_aRootCategory": {"_sName": "Characters"},
        "_aSubCategory": {"_sName": "Skins"}, "_aTags": ["skin"],
        "_aPreviewMedia": {"_sUrl": "https://images.example.test/preview.jpg"},
        "_bHasContentRatings": False,
    }
    value.update(updates)
    return value


class CollectorTests(unittest.TestCase):
    def test_normal_list_parse_and_unknown_rating(self):
        item = normalize_record(record(), GAME)
        self.assertEqual(item["item_id"], 101)
        self.assertEqual(item["game_id"], 8552)
        self.assertEqual(item["content_rating_status"], "UNKNOWN")

    def test_missing_author_image_and_update_fields(self):
        item = normalize_record(record(_aSubmitter=None, _aPreviewMedia=None), GAME)
        self.assertIsNone(item["author_name"])
        self.assertEqual(item["preview_urls"], [])
        self.assertIsNone(item["updated_at"])

    def test_deduplicate_source_type_id(self):
        item = normalize_record(record(), GAME)
        self.assertEqual(len(deduplicate([item, dict(item)])), 1)

    def test_wrong_game_is_recorded_and_skipped(self):
        response = Mock(status_code=200, headers={}, request=Mock(url="https://example.test"))
        response.json.return_value = {"_aRecords": [record(_aGame={"_idRow": 12})], "_aMetadata": {}}
        client = Mock()
        client.get.return_value = response
        result = collect_game(client, GAME, max_pages=1)
        self.assertEqual(result["records"], [])
        self.assertIn("mismatched", result["failure_reasons"][0]["reason"])

    def test_empty_list_and_max_page_is_incomplete(self):
        response = Mock(status_code=200, headers={}, request=Mock(url="https://example.test"))
        response.json.return_value = {"_aRecords": [], "_aMetadata": {}}
        client = Mock()
        client.get.return_value = response
        result = collect_game(client, GAME, max_pages=1)
        self.assertEqual(result["records"], [])
        self.assertFalse(result["complete_for_time_window"])
        self.assertEqual(result["status"], "incomplete")

    def test_invalid_json_is_failure_not_exception(self):
        response = Mock(status_code=200, headers={}, request=Mock(url="https://example.test"))
        response.json.side_effect = ValueError("bad json")
        client = Mock()
        client.get.return_value = response
        result = collect_game(client, GAME, max_pages=1)
        self.assertIn("Invalid JSON", result["failure_reasons"][0]["reason"])

    def test_connection_failure_is_recorded_and_retried_once(self):
        import httpx
        client = Mock()
        client.get.side_effect = httpx.ConnectError("offline")
        with patch("eryoutoolbox.gamebanana.time.sleep") as sleep:
            result = collect_game(client, GAME, max_pages=1)
        self.assertEqual(client.get.call_count, 2)
        self.assertIn("ConnectError", result["failure_reasons"][0]["reason"])
        sleep.assert_called_once_with(1.0)

    def test_rate_limit_stops_after_retry_after(self):
        response = Mock(status_code=429, headers={"Retry-After": "0"}, request=Mock(url="https://example.test"))
        client = Mock()
        client.get.return_value = response
        result = collect_game(client, GAME, max_pages=2)
        self.assertEqual(client.get.call_count, 1)
        self.assertFalse(result["complete_for_time_window"])
        self.assertIn("429", result["failure_reasons"][0]["reason"])

    def test_per_page_10_is_valid_and_last_page_is_normal(self):
        response = Mock(status_code=200, headers={}, request=Mock(url="https://example.test"))
        response.json.return_value = {"_aRecords": [record()],
                                      "_aMetadata": {"_nPerpage": 10, "_nRecordCount": 1}}
        client = Mock()
        client.get.return_value = response
        result = collect_game(client, GAME, max_pages=5, per_page=10)
        self.assertEqual(client.get.call_args.kwargs["params"]["_nPerpage"], 10)
        self.assertEqual(result["pagination_pages"][0]["classification"], "normal_last_page")
        self.assertEqual(result["pages_requested"], 1)

    def test_per_page_50_parses_all_matching_records(self):
        response = Mock(status_code=200, headers={}, request=Mock(url="https://example.test"))
        rows = [record(_idRow=1000 + index) for index in range(50)]
        response.json.return_value = {"_aRecords": rows,
                                      "_aMetadata": {"_nPerpage": 50, "_nRecordCount": 100}}
        client = Mock()
        client.get.return_value = response
        result = collect_game(client, GAME, max_pages=1, per_page=50)
        self.assertEqual(client.get.call_args.kwargs["params"]["_nPerpage"], 50)
        self.assertEqual(len(result["records"]), 50)
        self.assertTrue(all(item["game_id"] == 8552 for item in result["records"]))
        self.assertEqual(result["pagination_pages"][0]["classification"], "full_page")

    def test_per_page_51_and_zero_are_rejected(self):
        client = Mock()
        with self.assertRaisesRegex(ValueError, "1 and 50"):
            collect_game(client, GAME, per_page=51)
        with self.assertRaisesRegex(ValueError, "1 and 50"):
            collect_game(client, GAME, per_page=0)
        client.get.assert_not_called()

    def test_short_final_page_is_normal_and_stops_paging(self):
        first = Mock(status_code=200, headers={}, request=Mock(url="https://example.test"))
        first.json.return_value = {"_aRecords": [record(_idRow=1000 + i) for i in range(50)],
                                  "_aMetadata": {"_nPerpage": 50, "_nRecordCount": 75}}
        last = Mock(status_code=200, headers={}, request=Mock(url="https://example.test"))
        last.json.return_value = {"_aRecords": [record(_idRow=2000 + i) for i in range(25)],
                                 "_aMetadata": {"_nPerpage": 50, "_nRecordCount": 75}}
        client = Mock()
        client.get.side_effect = [first, last]
        result = collect_game(client, GAME, max_pages=5, per_page=50, delay=0)
        self.assertEqual(client.get.call_count, 2)
        self.assertEqual(result["pagination_pages"][-1]["classification"], "normal_last_page")
        self.assertEqual(result["actual_record_count"], 75)

    def test_server_page_limit_is_distinguished_from_failure(self):
        response = Mock(status_code=200, headers={}, request=Mock(url="https://example.test"))
        response.json.return_value = {"_aRecords": [record(_idRow=1000 + i) for i in range(10)],
                                      "_aMetadata": {"_nPerpage": 10, "_nRecordCount": 100}}
        client = Mock()
        client.get.return_value = response
        result = collect_game(client, GAME, max_pages=1, per_page=50)
        diagnostic = result["pagination_pages"][0]
        self.assertEqual(diagnostic["classification"], "server_page_limit")
        self.assertTrue(diagnostic["server_page_limit"])
        self.assertEqual(result["failure_reasons"], [])

    def test_metadata_count_mismatch_is_reported_as_abnormal(self):
        response = Mock(status_code=200, headers={}, request=Mock(url="https://example.test"))
        response.json.return_value = {"_aRecords": [record() for _ in range(49)],
                                      "_aMetadata": {"_nPerpage": 50, "_nRecordCount": 100}}
        client = Mock()
        client.get.return_value = response
        result = collect_game(client, GAME, max_pages=1, per_page=50)
        self.assertEqual(result["pagination_pages"][0]["classification"], "abnormal_response")
        self.assertTrue(result["failure_reasons"])

    def test_mismatched_game_is_still_excluded_from_50_rows(self):
        response = Mock(status_code=200, headers={}, request=Mock(url="https://example.test"))
        rows = [record(_idRow=1000 + i) for i in range(50)]
        rows[-1] = record(_idRow=2000, _aGame={"_idRow": 20357})
        response.json.return_value = {"_aRecords": rows,
                                      "_aMetadata": {"_nPerpage": 50, "_nRecordCount": 100}}
        client = Mock()
        client.get.return_value = response
        result = collect_game(client, GAME, max_pages=1, per_page=50)
        self.assertEqual(len(result["records"]), 49)
        self.assertTrue(all(item["game_id"] == 8552 for item in result["records"]))


if __name__ == "__main__":
    unittest.main()
