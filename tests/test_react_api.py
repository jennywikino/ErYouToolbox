from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from eryoutoolbox.database import connect_database, initialize_database  # noqa: E402
from react_api import ReadOnlyAPI  # noqa: E402


class ReactAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"
        initialize_database(self.path)
        connection = connect_database(self.path)
        self.images = [{"image_url": "https://images.gamebanana.com/img/ss/mods/original.jpg",
                        "thumbnail_url": "https://images.gamebanana.com/img/ss/mods/530-90_original.jpg",
                        "switch_url": "https://images.gamebanana.com/img/ss/mods/100-90_original.jpg"}]
        for number in range(1, 23):
            connection.execute(
                "INSERT INTO mods(source,item_type,item_id,game_id,title,author_name,category,"
                "preview_urls_json,first_seen_at,last_checked_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("gamebanana", "Mod", number, 8552 if number < 20 else 19567,
                 f"Sample {number}", "Saved Author", "Character",
                 json.dumps(self.images) if number == 1 else "[]",
                 "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            )
        connection.commit()
        connection.close()
        self.api = ReadOnlyAPI(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_pagination_cap_and_game_filter(self):
        status, page = self.api.get("/api/mods?game=19567&limit=2")
        self.assertEqual(status, 200)
        self.assertEqual(page["total_count"], 3)
        self.assertTrue(all(item["game_id"] == 19567 for item in page["items"]))
        _, next_page = self.api.get("/api/mods?game=19567&limit=2&offset=2")
        self.assertEqual(len(next_page["items"]), 1)
        self.assertNotEqual(page["items"][0]["item_id"], next_page["items"][0]["item_id"])
        self.assertEqual(self.api.get("/api/mods?limit=21")[0], 400)
        self.assertLessEqual(len(self.api.get("/api/mods?limit=20")[1]["items"]), 20)

    def test_search_and_images_only_use_saved_data(self):
        status, page = self.api.get("/api/mods?with_images=1&search=Sample%201")
        self.assertEqual(status, 200)
        self.assertEqual([item["item_id"] for item in page["items"]], [1])
        self.assertEqual(page["items"][0]["category"], "Character")

    def test_images_default_visible_and_explicit_preference_hides(self):
        target = "/api/mod?source=gamebanana&item_type=Mod&item_id=1"
        _, item = self.api.get(target + "&show_unrated=0")
        self.assertEqual(item["preview_images"], [])
        self.assertEqual(item["preview_urls"], [])
        self.assertEqual(item["preview_state"], "PREFERENCE_HIDDEN")
        _, item = self.api.get(target + "&show_unrated=1")
        self.assertEqual(item["preview_images"], self.images)
        self.assertEqual(item["item_id"], 1)

    def test_adult_urls_obey_image_preference(self):
        item = {"content_rating_status": "ADULT", "preview_urls": ["https://example.org/a.jpg"],
                "preview_images": self.images}
        result = self.api.image_policy(item, True)
        self.assertEqual(result["preview_urls"], item["preview_urls"])
        self.assertEqual(result["preview_images"], self.images)

    def test_normalized_metadata_retains_explicit_source_labels(self):
        from eryoutoolbox.models import normalize_record
        from eryoutoolbox.content_ratings import source_ratings
        normalized = normalize_record({'_idRow': 7, '_aContentRatings': {'sc': 'Sexual Content', 'pn': 'Partial Nudity'}}, {'game_id': 8552, 'name': 'Genshin Impact'})
        evidence = source_ratings(json.dumps({'_record': normalized}))
        self.assertEqual(evidence['codes'], ['sc', 'pn'])
        self.assertEqual(evidence['verification'], 'explicit_labels')
        self.assertEqual(normalized['content_rating_status'], 'UNKNOWN')

    def test_missing_or_malformed_labels_remain_unknown(self):
        from eryoutoolbox.content_ratings import source_ratings
        for raw in ('invalid JSON', '{}', json.dumps({'title': 'SFW safe', '_sInitialVisibility': 'show'}),
                    json.dumps({'_bHasContentRatings': True}), json.dumps({'_aContentRatings': []})):
            self.assertEqual(source_ratings(raw)['codes'], ['UNKNOWN'])
        self.assertEqual(source_ratings(json.dumps({'_record': {'has_content_ratings': False}}))['codes'], ['-'])

    def test_rating_or_filter_is_applied_before_pagination(self):
        connection = connect_database(self.path)
        for item_id, raw in [(1, {'_aContentRatings': {'sc': 'Sexual Content', 'pn': 'Partial Nudity'}}),
                             (2, {'_bHasContentRatings': False})]:
            connection.execute('UPDATE mods SET raw_metadata_json=? WHERE item_id=?', (json.dumps(raw), item_id))
        connection.commit()
        connection.close()
        _, page = self.api.get('/api/mods?ratings=sc,pn&limit=1')
        self.assertEqual(page['total_count'], 1)
        self.assertEqual(page['items'][0]['source_ratings']['codes'], ['sc', 'pn'])
        self.assertEqual(self.api.get('/api/mods?ratings=-')[1]['total_count'], 1)
        self.assertEqual(self.api.get('/api/mods?ratings=UNKNOWN')[1]['total_count'], 20)
        self.assertEqual(self.api.get('/api/mods?ratings=')[1]['total_count'], 0)
        self.assertEqual(self.api.get('/api/mods?ratings=fictional')[0], 400)

    def test_database_unchanged(self):
        before = hashlib.sha256(self.path.read_bytes()).digest()
        self.api.get("/api/mods")
        self.api.get("/api/mod?source=gamebanana&item_type=Mod&item_id=1&show_unrated=1")
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).digest())

    def test_latest_defaults_to_source_publication_not_local_discovery(self):
        connection = connect_database(self.path)
        connection.execute("UPDATE mods SET created_at='2020-01-01T00:00:00Z', first_seen_at='2026-10-28T00:00:00Z' WHERE item_id=1")
        connection.execute("UPDATE mods SET created_at='2026-10-20T00:00:00Z', first_seen_at='2026-01-01T00:00:00Z' WHERE item_id=2")
        connection.commit()
        connection.close()
        _, page = self.api.get('/api/mods?limit=1')
        self.assertEqual(page['items'][0]['item_id'], 2)
        _, discovered = self.api.get('/api/mods?sort=first_seen&limit=1')
        self.assertEqual(discovered['items'][0]['item_id'], 1)

    def test_recent_updates_exclude_missing_and_modified_only_records(self):
        connection = connect_database(self.path)
        connection.execute("UPDATE mods SET updated_at='2026-10-20T00:00:00.500Z',created_at='2020-01-01T00:00:00Z' WHERE item_id=1")
        connection.execute("UPDATE mods SET updated_at='2026-10-20T00:00:00Z' WHERE item_id=2")
        connection.execute("UPDATE mods SET modified_at='2099-01-01T00:00:00Z' WHERE item_id=3")
        connection.execute("UPDATE mods SET updated_at='invalid' WHERE item_id=4")
        connection.commit()
        connection.close()
        _, page = self.api.get('/api/mods?sort=updated&limit=1')
        self.assertEqual(page['total_count'], 2)
        self.assertEqual(page['items'][0]['item_id'], 1)
        self.assertIsNone(page['items'][0]['source_update_detected_at'])
        _, next_page = self.api.get('/api/mods?sort=updated&limit=1&offset=1')
        self.assertEqual(next_page['items'][0]['item_id'], 2)

    def test_source_update_event_uses_full_identity(self):
        connection = connect_database(self.path)
        connection.execute("INSERT INTO mods(source,item_type,item_id,first_seen_at,last_checked_at) VALUES('other','Mod',1,'now','now')")
        connection.execute("INSERT INTO mod_events(source,item_type,item_id,event_type,detected_at) VALUES('other','Mod',1,'source_updated','2026-10-29T00:00:00Z')")
        connection.commit()
        _, page = self.api.get('/api/mods?game=8552&search=1')
        saved = next(item for item in page['items'] if item['item_id'] == 1)
        self.assertIsNone(saved['source_update_detected_at'])
        connection.execute("INSERT INTO mod_events(source,item_type,item_id,event_type,detected_at) VALUES('gamebanana','Mod',1,'source_updated','2026-10-28T00:00:00Z')")
        connection.commit()
        connection.close()
        _, page = self.api.get('/api/mods?game=8552&search=1')
        self.assertEqual(next(item for item in page['items'] if item['item_id'] == 1)['source_update_detected_at'], '2026-10-28T00:00:00Z')

    def test_sync_metadata_scopes_game_and_preserves_failed_status(self):
        _, initial = self.api.get('/api/mods?game=8552')
        self.assertIsNone(initial['discovery']['last_sync'])
        connection = connect_database(self.path)
        for game, status, at in [(8552, 'success', '2026-10-26T00:00:00Z'),
                                 (8552, 'failed', '2026-10-27T00:00:00Z'),
                                 (19567, 'partial', '2026-10-28T00:00:00Z')]:
            connection.execute('INSERT INTO sync_runs(source,game_id,started_at,ended_at,status) VALUES(?,?,?,?,?)', ('gamebanana', game, at, at, status))
        connection.commit()
        connection.close()
        before = hashlib.sha256(self.path.read_bytes()).digest()
        _, scoped = self.api.get('/api/mods?game=8552&search=nonexistent')
        self.assertEqual(scoped['total_count'], 0)
        self.assertEqual(scoped['discovery']['local_count'], 19)
        self.assertEqual(scoped['discovery']['last_sync']['status'], 'failed')
        self.assertEqual(scoped['discovery']['coverage'], 'unverified')
        _, all_games = self.api.get('/api/mods')
        self.assertEqual(all_games['discovery']['last_sync']['game_id'], 19567)
        self.assertEqual(all_games['discovery']['local_count'], 22)
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).digest())

    def test_missing_database_and_invalid_requests(self):
        self.assertEqual(ReadOnlyAPI(self.path.with_name("missing.db")).get("/api/mods")[0], 503)
        self.assertEqual(self.api.get("/api/mods?sort=invalid")[0], 400)
        self.assertEqual(self.api.get("/api/mods?game=999")[0], 400)
        self.assertEqual(self.api.get("/api/mod?item_id=1")[0], 400)
        self.assertEqual(self.api.get("/api/mod?source=gamebanana&item_type=Mod&item_id=99")[0], 404)


if __name__ == "__main__":
    unittest.main()
