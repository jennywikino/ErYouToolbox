from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.database import initialize_database  # noqa: E402
from eryoutoolbox.ui_queries import (  # noqa: E402
    DatabaseReadError,
    distribute_items_to_columns,
    gallery_step_index,
    parse_preview_data,
    parse_gallery_urls,
    parse_preview_images,
    preview_display_decision,
    preview_urls_for_display,
    query_mod_detail,
    query_mods,
    valid_http_url,
)


class UIQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "ui.db"
        initialize_database(self.db_path)
        connection = sqlite3.connect(self.db_path)
        rows = [
            ("gamebanana", "Mod", 101, 8552, "Genshin Impact", "Alpha Pack", "Author Ana",
             "2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z", "2026-01-02T00:00:00Z",
             "UNKNOWN", '["https://img.example.test/a.jpg"]'),
            ("gamebanana", "Mod", 102, 20357, "Wuthering Waves", "Beta Pack", "Author Bob",
             "2026-01-02T00:00:00Z", None, "2026-01-04T00:00:00Z",
             "SAFE", '["https://img.example.test/b.jpg"]'),
            ("gamebanana", "Mod", 103, 8552, "Genshin Impact", "Gamma", "Author Ana",
             None, None, "2026-01-01T00:00:00Z", "UNKNOWN", None),
        ]
        for source, item_type, item_id, game_id, game_name, title, author, created, updated, seen, rating, previews in rows:
            connection.execute(
                "INSERT INTO mods (source,item_type,item_id,game_id,game_name,title,author_name,created_at,updated_at,first_seen_at,content_rating_status,preview_urls_json,last_checked_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (source, item_type, item_id, game_id, game_name, title, author, created, updated,
                 seen, rating, previews, "2026-01-05T00:00:00Z"),
            )
        connection.execute(
            "INSERT INTO user_states (source,item_type,item_id,is_read,is_favorite,workflow_status,updated_at) VALUES (?,?,?,?,?,?,?)",
            ("gamebanana", "Mod", 101, 1, 1, "to_repost", "2026-01-05T00:00:00Z"),
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_reads_mod_and_read_only_user_state(self):
        result = query_mods(self.db_path)
        self.assertEqual(result["total_count"], 3)
        item = next(item for item in result["items"] if item["item_id"] == 101)
        self.assertEqual(item["title"], "Alpha Pack")
        self.assertEqual(item["is_favorite"], 1)
        self.assertEqual(item["workflow_status"], "to_repost")

    def test_game_filter(self):
        result = query_mods(self.db_path, game_id=8552)
        self.assertEqual(result["total_count"], 2)
        self.assertTrue(all(item["game_id"] == 8552 for item in result["items"]))

    def test_title_and_author_search(self):
        self.assertEqual(query_mods(self.db_path, search="beta")["items"][0]["item_id"], 102)
        result = query_mods(self.db_path, search="ana")
        self.assertEqual(result["total_count"], 2)

    def test_exact_mod_id_search(self):
        connection = sqlite3.connect(self.db_path)
        connection.execute("UPDATE mods SET item_id=732438 WHERE item_id=103")
        connection.commit()
        connection.close()
        result = query_mods(self.db_path, search="732438")
        self.assertEqual([item["item_id"] for item in result["items"]], [732438])

    def test_limit_offset_pagination(self):
        first = query_mods(self.db_path, sort="first_seen", limit=2, offset=0)
        second = query_mods(self.db_path, sort="first_seen", limit=2, offset=2)
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(len(second["items"]), 1)
        self.assertTrue(set(x["item_id"] for x in first["items"]).isdisjoint(
            x["item_id"] for x in second["items"]))

    def test_preview_test_area_follows_game_and_search_filters(self):
        all_games = query_mods(self.db_path, sort="first_seen", limit=4, require_preview=True)["items"]
        self.assertEqual({item["item_id"] for item in all_games}, {101, 102})
        genshin = query_mods(self.db_path, game_id=8552, limit=4, require_preview=True)["items"]
        self.assertEqual([item["item_id"] for item in genshin], [101])
        star_rail = query_mods(self.db_path, game_id=18366, limit=4, require_preview=True)["items"]
        self.assertEqual(star_rail, [])
        searched = query_mods(self.db_path, game_id=8552, search="101",
                              limit=4, require_preview=True)["items"]
        self.assertEqual([item["item_id"] for item in searched], [101])

    def test_column_distribution_is_stable_without_loss_or_duplicates(self):
        items = [{"item_id": item_id} for item_id in range(1, 11)]
        columns = distribute_items_to_columns(items, 4)
        flattened = [item["item_id"] for column in columns for item in column]
        self.assertEqual([item["item_id"] for item in columns[0]], [1, 5, 9])
        self.assertEqual(sorted(flattened), list(range(1, 11)))
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_sort_options(self):
        created = query_mods(self.db_path, sort="created")["items"]
        updated = query_mods(self.db_path, sort="updated")["items"]
        first_seen = query_mods(self.db_path, sort="first_seen")["items"]
        self.assertEqual(created[0]["item_id"], 102)
        self.assertEqual(updated[0]["item_id"], 101)
        self.assertEqual(first_seen[0]["item_id"], 102)

    def test_missing_image_and_time_fields(self):
        result = query_mods(self.db_path, search="gamma")
        item = result["items"][0]
        self.assertEqual(item["preview_urls"], [])
        self.assertIsNone(item["created_at"])
        self.assertIsNone(item["updated_at"])

    def test_missing_database_reports_error_without_creating_it(self):
        missing = Path(self.temp.name) / "missing.db"
        with self.assertRaisesRegex(DatabaseReadError, "does not exist"):
            query_mods(missing)
        self.assertFalse(missing.exists())

    def test_queries_do_not_modify_database(self):
        before = hashlib.sha256(self.db_path.read_bytes()).digest()
        query_mods(self.db_path, game_id=8552, search="a", sort="updated", limit=1)
        after = hashlib.sha256(self.db_path.read_bytes()).digest()
        self.assertEqual(before, after)

    def test_unknown_preview_is_hidden_unless_enabled_for_session(self):
        item = query_mods(self.db_path, search="alpha")["items"][0]
        self.assertEqual(preview_urls_for_display(item), [])
        self.assertEqual(preview_urls_for_display(item, show_unrated=True),
                         ["https://img.example.test/a.jpg"])
        self.assertEqual(preview_urls_for_display({**item, "content_rating_status": "ADULT"}, True), [])

    def test_valid_image_url_is_ready_for_sfw_display(self):
        item = {"content_rating_status": "SAFE",
                "preview_urls": ["https://images.example.test/p.jpg"]}
        self.assertEqual(preview_display_decision(item),
                         ("DISPLAY", ["https://images.example.test/p.jpg"]))

    def test_missing_image_has_no_image_state(self):
        self.assertEqual(preview_display_decision({"content_rating_status": "SAFE",
                                                   "preview_urls": []}), ("NO_IMAGE", []))

    def test_invalid_url_is_reported_separately(self):
        urls, invalid = parse_preview_data('["javascript:alert(1)"]')
        self.assertEqual(urls, [])
        self.assertTrue(invalid)
        self.assertEqual(preview_display_decision({"content_rating_status": "SAFE",
                                                   "preview_urls": urls,
                                                   "preview_invalid": invalid}),
                         ("INVALID_URL", []))

    def test_unknown_image_is_hidden_by_default_and_enabled_per_session(self):
        item = {"content_rating_status": "UNKNOWN",
                "preview_urls": ["https://images.example.test/u.jpg"]}
        self.assertEqual(preview_display_decision(item), ("UNKNOWN_HIDDEN", []))
        self.assertEqual(preview_display_decision(item, show_unrated=True),
                         ("DISPLAY", ["https://images.example.test/u.jpg"]))

    def test_adult_image_remains_hidden_when_unrated_toggle_is_on(self):
        item = {"content_rating_status": "ADULT",
                "preview_urls": ["https://images.example.test/a.jpg"]}
        self.assertEqual(preview_display_decision(item, show_unrated=True),
                         ("NSFW_HIDDEN", []))

    def test_gallery_preserves_order_and_collapses_resolution_variants(self):
        raw = json.dumps([
            "https://images.gamebanana.com/img/ss/mods/530-90_shared.jpg",
            "https://images.gamebanana.com/img/ss/mods/100-90_shared.jpg",
            "https://images.gamebanana.com/img/ss/mods/530-90_second.jpg",
            "https://images.gamebanana.com/img/ss/mods/530-90_second.jpg",
        ])
        urls, invalid = parse_gallery_urls(raw)
        self.assertFalse(invalid)
        self.assertEqual(urls, [
            "https://images.gamebanana.com/img/ss/mods/530-90_shared.jpg",
            "https://images.gamebanana.com/img/ss/mods/530-90_second.jpg",
        ])

    def test_rich_and_legacy_preview_formats_select_appropriate_urls(self):
        rich = json.dumps([{
            "image_url": "https://images.gamebanana.com/img/ss/mods/original.jpg",
            "thumbnail_url": "https://images.gamebanana.com/img/ss/mods/530-90_card.jpg",
            "switch_url": "https://images.gamebanana.com/img/ss/mods/100-90_small.jpg",
        }])
        images, invalid = parse_preview_images(rich)
        self.assertFalse(invalid)
        self.assertEqual(images[0]["image_url"].rsplit("/", 1)[-1], "original.jpg")
        self.assertEqual(images[0]["thumbnail_url"].rsplit("/", 1)[-1], "530-90_card.jpg")
        self.assertEqual(images[0]["switch_url"].rsplit("/", 1)[-1], "100-90_small.jpg")
        self.assertEqual(parse_preview_data(rich)[0], [images[0]["thumbnail_url"]])
        legacy, legacy_invalid = parse_preview_images(
            '["https://images.gamebanana.com/img/ss/mods/530-90_legacy.jpg"]')
        self.assertFalse(legacy_invalid)
        self.assertEqual(legacy[0]["image_url"], legacy[0]["thumbnail_url"])

    def test_invalid_original_falls_back_to_valid_thumbnail_only(self):
        raw = json.dumps([{"image_url": "javascript:alert(1)",
                           "thumbnail_url": "https://images.gamebanana.com/img/ss/mods/100-90_ok.jpg"}])
        images, invalid = parse_preview_images(raw)
        self.assertTrue(invalid is False)
        self.assertEqual(images[0]["image_url"], images[0]["thumbnail_url"])

    def test_gallery_empty_and_index_boundaries(self):
        self.assertEqual(parse_gallery_urls("[]"), ([], False))
        self.assertEqual(gallery_step_index(0, 0, 1), 0)
        self.assertEqual(gallery_step_index(0, 3, -1), 0)
        self.assertEqual(gallery_step_index(2, 3, 1), 2)
        self.assertEqual(gallery_step_index(1, 3, 1), 2)

    def test_author_link_requires_safe_http_url(self):
        self.assertTrue(valid_http_url("https://gamebanana.com/members/123"))
        self.assertFalse(valid_http_url("javascript:alert(1)"))
        self.assertFalse(valid_http_url("https://user:pass@gamebanana.com/members/123"))
        self.assertFalse(valid_http_url("https://gamebanana.com:bad/members/123"))

    def test_detail_reads_saved_fields_and_images(self):
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "UPDATE mods SET preview_urls_json=?,author_id=123,author_url=?,category=?,subcategory=?,tags_json=? WHERE item_id=101",
            (json.dumps([
                {"image_url": "https://images.gamebanana.com/img/ss/mods/one.jpg",
                 "thumbnail_url": "https://images.gamebanana.com/img/ss/mods/530-90_one.jpg",
                 "switch_url": "https://images.gamebanana.com/img/ss/mods/100-90_one.jpg"},
                {"image_url": "https://images.gamebanana.com/img/ss/mods/two.jpg",
                 "thumbnail_url": "https://images.gamebanana.com/img/ss/mods/530-90_two.jpg",
                 "switch_url": "https://images.gamebanana.com/img/ss/mods/100-90_two.jpg"},
            ]), "https://gamebanana.com/members/123", "Character", "Outfit", '["blue"]'),
        )
        connection.commit()
        connection.close()
        detail = query_mod_detail(self.db_path, source="gamebanana", item_type="Mod", item_id=101)
        self.assertEqual(detail["preview_images"], [
            {"image_url": "https://images.gamebanana.com/img/ss/mods/one.jpg",
             "thumbnail_url": "https://images.gamebanana.com/img/ss/mods/530-90_one.jpg",
             "switch_url": "https://images.gamebanana.com/img/ss/mods/100-90_one.jpg"},
            {"image_url": "https://images.gamebanana.com/img/ss/mods/two.jpg",
             "thumbnail_url": "https://images.gamebanana.com/img/ss/mods/530-90_two.jpg",
             "switch_url": "https://images.gamebanana.com/img/ss/mods/100-90_two.jpg"},
        ])
        self.assertEqual(detail["author_id"], 123)
        self.assertEqual(detail["tags"], ["blue"])
        self.assertEqual(detail["content_rating_status"], "UNKNOWN")
        self.assertIsNone(detail["description"])
        self.assertEqual(preview_display_decision(detail), ("UNKNOWN_HIDDEN", []))
        self.assertEqual(preview_display_decision(detail, show_unrated=True)[1], [
            "https://images.gamebanana.com/img/ss/mods/one.jpg",
            "https://images.gamebanana.com/img/ss/mods/two.jpg",
        ])

    def test_detail_missing_record_returns_none(self):
        self.assertIsNone(query_mod_detail(self.db_path, source="gamebanana",
                                           item_type="Mod", item_id=999999))

    def test_detail_and_id_search_do_not_modify_database(self):
        before = hashlib.sha256(self.db_path.read_bytes()).digest()
        query_mods(self.db_path, search="101")
        query_mod_detail(self.db_path, source="gamebanana", item_type="Mod", item_id=101)
        after = hashlib.sha256(self.db_path.read_bytes()).digest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
