from __future__ import annotations

from datetime import datetime, timezone
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from eryoutoolbox.database import connect_database, initialize_database  # noqa: E402
from eryoutoolbox.importer import import_samples  # noqa: E402
from backfill_previews import (  # noqa: E402
    GAMES,
    collect_preview_pages,
    checkpoint_resume_page,
    fetch_exact_item,
    load_checkpoint,
    load_games,
    main,
    open_existing_database,
    plan_preview_updates,
    run_backfill,
    save_checkpoint,
)


IMAGE = "https://images.gamebanana.com/img/ss/mods/sample.jpg"


def mod(item_id: int = 42, title: str = "Same title", previews=None) -> dict:
    return {
        "source": "gamebanana", "item_type": "Mod", "item_id": item_id,
        "game_id": 8552, "game_name": "Genshin Impact", "title": title,
        "original_url": f"https://gamebanana.com/mods/{item_id}",
        "author_id": 7, "author_name": "Author", "author_url": None,
        "created_at": "2026-01-01T00:00:00Z", "modified_at": None,
        "updated_at": None, "version": None, "category": None,
        "subcategory": None, "tags": [], "preview_urls": previews or [],
        "content_rating_status": "UNKNOWN",
    }


class PreviewBackfillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.db_path = Path(self.temporary.name) / "test.db"
        initialize_database(self.db_path)
        self.connection = connect_database(self.db_path)
        snapshot_time = datetime(2026, 10, 1, tzinfo=timezone.utc)
        imported = import_samples(
            self.connection,
            [({"path": "fixture", "captured_at": snapshot_time}, [mod()])],
            dry_run=False,
        )
        self.assertEqual(imported["inserted"], 1)
        self.connection.execute(
            "UPDATE user_states SET is_read=1,is_favorite=1,note='keep',workflow_status='to_repost'"
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()
        self.temporary.cleanup()

    def record(self, item_id=42, title="Different title", urls=None):
        value = mod(item_id=item_id, title=title)
        value["preview_urls"] = urls if urls is not None else [IMAGE]
        return value

    def test_matches_by_composite_identity_not_title(self):
        result = plan_preview_updates(self.connection, [self.record(title="not the DB title")])
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["sample_ids"], [42])
        self.assertEqual(result["records_to_update"], 1)

    def test_image_url_is_written_to_preview_field_only(self):
        result = run_backfill(self.connection, [self.record()], dry_run=False,
                              before_write=lambda: None)
        self.assertEqual(result["updated"], 1)
        row = self.connection.execute(
            "SELECT title,author_name,created_at,updated_at,first_seen_at,last_checked_at,"
            "preview_urls_json,content_rating_status FROM mods"
        ).fetchone()
        self.assertEqual(row["preview_urls_json"], json.dumps([IMAGE], separators=(",", ":")))
        self.assertEqual((row["title"], row["author_name"], row["content_rating_status"]),
                         ("Same title", "Author", "UNKNOWN"))

    def test_rich_image_metadata_is_not_downgraded_to_thumbnail_strings(self):
        image = {"image_url": "https://images.gamebanana.com/img/ss/mods/original.jpg",
                 "thumbnail_url": "https://images.gamebanana.com/img/ss/mods/530-90_card.jpg",
                 "switch_url": "https://images.gamebanana.com/img/ss/mods/100-90_small.jpg",
                 "original_verified": True}
        value = self.record(urls=[image["thumbnail_url"]])
        value["preview_images"] = [image]
        result = run_backfill(self.connection, [value], dry_run=False,
                              before_write=lambda: None)
        stored = json.loads(self.connection.execute(
            "SELECT preview_urls_json FROM mods"
        ).fetchone()[0])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(stored, [{key: value for key, value in image.items()
                                   if key != "original_verified"}])

    def test_dry_run_changes_only_the_exact_target_candidate(self):
        snapshot_time = datetime(2026, 10, 2, tzinfo=timezone.utc)
        import_samples(
            self.connection,
            [({"path": "fixture-2", "captured_at": snapshot_time}, [mod(item_id=43)])],
            dry_run=False,
        )
        before = tuple(self.connection.execute(
            "SELECT title,preview_urls_json FROM mods WHERE item_id=43"
        ).fetchone())
        result = run_backfill(self.connection, [self.record(item_id=42)], dry_run=True)
        after = tuple(self.connection.execute(
            "SELECT title,preview_urls_json FROM mods WHERE item_id=43"
        ).fetchone())
        self.assertEqual(result["sample_ids"], [42])
        self.assertEqual(before, after)

    def test_exact_api_record_uses_only_real_sfile_for_original(self):
        from unittest.mock import Mock
        entries = [{"_sFile": f"original-{i}.jpg", "_sFile100": f"100-90-{i}.jpg",
                    "_sFile220": f"220-90-{i}.jpg", "_sFile530": f"530-90-{i}.jpg"}
                   for i in range(6)]
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"_aPreviewMedia": {
            "_sBaseUrl": "https://images.gamebanana.com/img/ss/mods", "_aImages": entries}}
        client = Mock()
        client.get.return_value = response
        result = fetch_exact_item(client, 732438)
        self.assertEqual(client.get.call_count, 1)
        self.assertEqual(client.get.call_args.args[0],
                         "https://gamebanana.com/apiv11/Mod/732438/ProfilePage")
        self.assertEqual(result["image_count"], 6)
        self.assertEqual(result["verified_original_count"], 6)
        image = result["records"][0]["preview_images"][0]
        self.assertEqual(image["image_url"], "https://images.gamebanana.com/img/ss/mods/original-0.jpg")
        self.assertEqual(image["thumbnail_url"], "https://images.gamebanana.com/img/ss/mods/530-90-0.jpg")
        self.assertEqual(image["switch_url"], "https://images.gamebanana.com/img/ss/mods/100-90-0.jpg")
        self.assertTrue(image["original_verified"])

    def test_missing_sfile_never_becomes_a_fake_original_candidate(self):
        from unittest.mock import Mock
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"_aPreviewMedia": {
            "_sBaseUrl": "https://images.gamebanana.com/img/ss/mods",
            "_aImages": [{"_sFile100": "100-90-only.jpg"}]}}
        client = Mock()
        client.get.return_value = response
        result = fetch_exact_item(client, 732438)
        self.assertEqual(result["image_count"], 1)
        self.assertEqual(result["verified_original_count"], 0)
        self.assertEqual(result["records"][0]["preview_images"], [])

    def test_no_image_is_skipped(self):
        result = run_backfill(self.connection, [self.record(urls=[])], dry_run=True)
        self.assertEqual(result["records_to_update"], 0)
        self.assertGreaterEqual(result["skipped"], 1)

    def test_repeated_apply_is_idempotent(self):
        first = run_backfill(self.connection, [self.record()], dry_run=False,
                             before_write=lambda: None)
        second = run_backfill(self.connection, [self.record()], dry_run=False,
                              before_write=lambda: self.fail("unchanged data must not back up"))
        self.assertEqual(first["updated"], 1)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["records_to_update"], 0)

    def test_user_state_is_preserved(self):
        before = tuple(self.connection.execute(
            "SELECT is_read,is_favorite,is_ignored,workflow_status,note,published_url FROM user_states"
        ).fetchone())
        run_backfill(self.connection, [self.record()], dry_run=False,
                     before_write=lambda: None)
        after = tuple(self.connection.execute(
            "SELECT is_read,is_favorite,is_ignored,workflow_status,note,published_url FROM user_states"
        ).fetchone())
        self.assertEqual(after, before)

    def test_no_mod_events_are_created(self):
        before = self.connection.execute("SELECT COUNT(*) FROM mod_events").fetchone()[0]
        run_backfill(self.connection, [self.record()], dry_run=False,
                     before_write=lambda: None)
        after = self.connection.execute("SELECT COUNT(*) FROM mod_events").fetchone()[0]
        self.assertEqual(after, before)

    def test_dry_run_has_no_database_side_effects(self):
        before = tuple(self.connection.execute(
            "SELECT title,preview_urls_json,first_seen_at,last_checked_at FROM mods"
        ).fetchone())
        result = run_backfill(self.connection, [self.record()], dry_run=True,
                              before_write=lambda: self.fail("dry-run must not back up"))
        after = tuple(self.connection.execute(
            "SELECT title,preview_urls_json,first_seen_at,last_checked_at FROM mods"
        ).fetchone())
        self.assertEqual(result["records_to_update"], 1)
        self.assertEqual(after, before)

    def test_default_database_open_is_read_only(self):
        connection = open_existing_database(self.db_path)
        try:
            with self.assertRaisesRegex(Exception, "readonly"):
                connection.execute("UPDATE mods SET preview_urls_json='[]'")
        finally:
            connection.close()

    def test_backup_failure_prevents_writes(self):
        before = self.connection.execute("SELECT preview_urls_json FROM mods").fetchone()[0]

        def fail_backup():
            raise OSError("backup failed")

        with self.assertRaisesRegex(OSError, "backup failed"):
            run_backfill(self.connection, [self.record()], dry_run=False,
                         before_write=fail_backup)
        after = self.connection.execute("SELECT preview_urls_json FROM mods").fetchone()[0]
        self.assertEqual(after, before)

    def test_one_backup_callback_for_the_batch(self):
        snapshot_time = datetime(2026, 10, 2, tzinfo=timezone.utc)
        import_samples(
            self.connection,
            [({"path": "fixture-2", "captured_at": snapshot_time}, [mod(item_id=43)])],
            dry_run=False,
        )
        calls = []
        result = run_backfill(self.connection,
                              [self.record(item_id=42), self.record(item_id=43)],
                              dry_run=False, before_write=lambda: calls.append("backup"))
        self.assertEqual(result["updated"], 2)
        self.assertEqual(calls, ["backup"])

    def test_missing_identity_match_is_reported(self):
        result = run_backfill(self.connection, [self.record(item_id=999)], dry_run=True)
        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["records_to_update"], 0)
        self.assertGreaterEqual(result["skipped"], 1)

    def test_other_game_id_is_not_matched(self):
        row = self.record()
        row["game_id"] = 18366
        result = plan_preview_updates(self.connection, [row])
        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["records_to_update"], 0)

    def test_zenless_target_game_is_matched_by_composite_identity(self):
        zenless_game = {"name": "Zenless Zone Zero", "game_id": 19567}
        zenless_mod = mod(item_id=99, title="ZZZ sample")
        zenless_mod["game_id"] = zenless_game["game_id"]
        zenless_mod["game_name"] = zenless_game["name"]
        import_samples(
            self.connection,
            [({"path": "zenless-fixture",
               "captured_at": datetime(2026, 10, 3, tzinfo=timezone.utc)},
              [zenless_mod])],
            dry_run=False,
        )
        incoming = self.record(item_id=99)
        incoming["game_id"] = zenless_game["game_id"]
        result = run_backfill(self.connection, [incoming], dry_run=True, game=zenless_game)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["sample_ids"], [99])
        self.assertEqual(result["records_to_update"], 1)

    def test_fifty_record_limit_is_supported(self):
        result = plan_preview_updates(self.connection, [self.record()], limit=50)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["records_to_update"], 1)

    def test_missing_image_fields_are_counted(self):
        result = plan_preview_updates(self.connection, [self.record(urls=[])])
        self.assertEqual(result["no_image_or_invalid"], 1)

    def test_valid_existing_urls_are_not_replaced_by_empty_values(self):
        self.connection.execute("UPDATE mods SET preview_urls_json=?", (json.dumps([IMAGE]),))
        self.connection.commit()
        result = run_backfill(self.connection, [self.record(urls=[])], dry_run=False,
                              before_write=lambda: self.fail("empty URL set should not back up"))
        self.assertEqual(result["updated"], 0)
        self.assertEqual(json.loads(self.connection.execute(
            "SELECT preview_urls_json FROM mods"
        ).fetchone()[0]), [IMAGE])

    def test_existing_original_metadata_is_skipped(self):
        original = "https://images.gamebanana.com/img/ss/mods/full.jpg"
        self.connection.execute("UPDATE mods SET preview_urls_json=?", (json.dumps([
            {"image_url": original, "thumbnail_url": IMAGE, "switch_url": IMAGE}
        ]),))
        self.connection.commit()
        result = plan_preview_updates(self.connection, [self.record()])
        self.assertEqual(result["already_highres"], 1)
        self.assertEqual(result["records_to_update"], 0)

    def test_thumbnail_object_is_not_used_as_original(self):
        result = plan_preview_updates(self.connection, [{
            **self.record(urls=[]),
            "preview_images": [{"thumbnail_url": IMAGE, "switch_url": IMAGE,
                                "original_verified": False}],
        }])
        self.assertEqual(result["records_to_update"], 0)
        self.assertGreaterEqual(result["no_image_or_invalid"], 1)


def index_record(item_id: int, *, game_id: int = 19567) -> dict:
    return {
        "_idRow": item_id, "_sModelName": "Mod", "_sName": f"MOD {item_id}",
        "_aGame": {"_idRow": game_id},
        "_aPreviewMedia": {
            "_sBaseUrl": "https://images.gamebanana.com/img/ss/mods",
            "_aImages": [{"_sFile": f"{item_id}.jpg",
                          "_sFile530": f"530-90_{item_id}.jpg",
                          "_sFile100": f"100-90_{item_id}.jpg"}],
        },
    }


def index_response(rows: list[dict], *, page_size: int = 2, total: int = 20) -> Mock:
    response = Mock(status_code=200)
    response.headers = {}
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "_aRecords": rows,
        "_aMetadata": {"_nPerpage": page_size, "_nRecordCount": total, "_nPage": 1},
    }
    return response


class PreviewPageCollectionTests(unittest.TestCase):
    def test_loads_all_six_configured_games(self):
        self.assertEqual([g["game_id"] for g in load_games()],
                         [8552, 18366, 19567, 20357, 21842, 23012])
        self.assertEqual(len(GAMES), 6)

    def test_start_page_and_bounded_pages_are_used_and_deduplicated(self):
        client = Mock()
        client.get.side_effect = [
            index_response([index_record(71), index_record(72)]),
            index_response([index_record(72), index_record(73)]),
        ]
        with patch("backfill_previews.time.sleep"):
            result = collect_preview_pages(client, GAMES[2], start_page=6,
                                           max_pages=2, per_page=2, delay=0)
        self.assertEqual(result["pages_scanned"], 2)
        self.assertEqual(result["request_count"], 2)
        self.assertEqual(result["raw_record_count"], 4)
        self.assertEqual([record["item_id"] for record in result["records"]], [71, 72, 73])
        self.assertEqual([call.kwargs["params"]["_nPage"] for call in client.get.call_args_list], [6, 7])
        self.assertTrue(all(call.kwargs["params"]["_aFilters[Generic_Game]"] == 19567
                            for call in client.get.call_args_list))
        self.assertEqual(result["next_page"], 8)
        self.assertFalse(result["exhausted"])

    def test_mismatched_game_stops_at_page_and_does_not_accept_record(self):
        client = Mock()
        client.get.return_value = index_response([index_record(71), index_record(72, game_id=8552)])
        with patch("backfill_previews.time.sleep"):
            result = collect_preview_pages(client, GAMES[2], max_pages=3, per_page=2, delay=0)
        self.assertEqual(result["records"][0]["item_id"], 71)
        self.assertEqual(result["failed_pages"], [1])
        self.assertEqual(result["next_page"], 1)
        self.assertEqual(client.get.call_count, 1)

    def test_rate_limit_records_retry_after_and_stops_without_more_requests(self):
        response = Mock(status_code=429, headers={"Retry-After": "60"})
        client = Mock()
        client.get.return_value = response
        result = collect_preview_pages(client, GAMES[2], max_pages=5, per_page=10, delay=0)
        self.assertEqual(client.get.call_count, 1)
        self.assertEqual(result["failed_pages"], [1])
        self.assertTrue(result["rate_limited"])
        self.assertEqual(result["failure_reasons"][0]["retry_after_seconds"], 60)
        self.assertEqual(result["next_page"], 1)

    def test_transient_request_error_retries_only_once(self):
        client = Mock()
        client.get.side_effect = [httpx.ConnectError("temporary"),
                                  index_response([index_record(71)], total=1)]
        with patch("backfill_previews.time.sleep"):
            result = collect_preview_pages(client, GAMES[2], max_pages=1, per_page=2, delay=0)
        self.assertEqual(client.get.call_count, 2)
        self.assertEqual(result["request_count"], 2)
        self.assertEqual(result["records"][0]["item_id"], 71)

    def test_scan_limits_reject_unbounded_page_or_item_requests(self):
        client = Mock()
        with self.assertRaisesRegex(ValueError, "max_pages"):
            collect_preview_pages(client, GAMES[2], max_pages=21)
        with self.assertRaisesRegex(ValueError, "per_page"):
            collect_preview_pages(client, GAMES[2], per_page=51)
        self.assertEqual(client.get.call_count, 0)

    def test_invalid_json_is_saved_as_a_failed_page(self):
        response = Mock(status_code=200, headers={})
        response.json.side_effect = ValueError("not JSON")
        client = Mock()
        client.get.return_value = response
        result = collect_preview_pages(client, GAMES[2], max_pages=2, per_page=2, delay=0)
        self.assertEqual(result["failed_pages"], [1])
        self.assertIn("Invalid JSON", result["failure_reasons"][0]["reason"])
        self.assertEqual(client.get.call_count, 1)

    def test_checkpoint_is_bound_to_game_and_resumes_next_page(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "checkpoint.json"
            data = {"format": "eryoutoolbox-preview-backfill-v1", "game_id": 19567,
                    "next_page": 12, "exhausted": False}
            save_checkpoint(path, data)
            self.assertEqual(load_checkpoint(path, GAMES[2], required=True)["next_page"], 12)
            self.assertEqual(checkpoint_resume_page({"next_page": 12, "pending_apply": False}, apply=True), 12)
            self.assertEqual(checkpoint_resume_page({"next_page": 15, "apply_next_page": 12,
                                                     "pending_apply": True}, apply=True), 12)
            self.assertEqual(checkpoint_resume_page({"next_page": 15, "apply_next_page": 12,
                                                     "pending_apply": True}, apply=False), 15)
            with self.assertRaisesRegex(ValueError, "game identity"):
                load_checkpoint(path, GAMES[1], required=True)

    def test_checkpoint_refuses_to_overwrite_unrecognized_file(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "existing.json"
            path.write_text("user data", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checkpoint"):
                save_checkpoint(path, {"format": "eryoutoolbox-preview-backfill-v1",
                                       "game_id": 19567, "next_page": 2})
            self.assertEqual(path.read_text(encoding="utf-8"), "user data")

    def test_dry_run_does_not_create_or_advance_checkpoint(self):
        import backfill_previews

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            project = Path(directory)
            database = project / "data" / "eryoutoolbox.db"
            initialize_database(database)
            connection = connect_database(database)
            fixture = mod(item_id=501, previews=[])
            fixture["game_id"] = 19567
            fixture["game_name"] = "Zenless Zone Zero"
            import_samples(
                connection,
                [({"path": "fixture", "captured_at": datetime(2026, 10, 1, tzinfo=timezone.utc)},
                  [fixture])],
                dry_run=False,
            )
            connection.close()

            client = Mock()
            client.get.return_value = index_response([index_record(501)], page_size=2, total=1)
            context = MagicMock()
            context.__enter__.return_value = client
            context.__exit__.return_value = False
            output = io.StringIO()
            with patch.object(backfill_previews, "ROOT", project), \
                    patch.object(backfill_previews.httpx, "Client", return_value=context), \
                    redirect_stdout(output):
                status = main(["--game", "19567", "--max-pages", "1", "--per-page", "2",
                               "--limit", "1", "--dry-run"])

            self.assertEqual(status, 0)
            self.assertIn("扫描页数：1", output.getvalue())
            checkpoint_path = project / "logs" / "preview_backfill" / "game_19567_checkpoint.json"
            self.assertFalse(checkpoint_path.exists())
            self.assertIn("本次已更新：False", output.getvalue())
            self.assertFalse((project / "data" / "backups").exists())
            readonly = open_existing_database(database)
            try:
                previews = readonly.execute("SELECT preview_urls_json FROM mods").fetchone()[0]
            finally:
                readonly.close()
            self.assertEqual(previews, "[]")

    def test_dry_run_apply_then_resume_advances_only_committed_pages(self):
        import backfill_previews

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            project = Path(directory)
            database = project / "data" / "eryoutoolbox.db"
            initialize_database(database)
            connection = connect_database(database)
            fixture = mod(item_id=502, previews=[])
            fixture.update(game_id=19567, game_name="Zenless Zone Zero")
            import_samples(connection, [({"path": "fixture", "captured_at":
                            datetime(2026, 10, 1, tzinfo=timezone.utc)}, [fixture])], dry_run=False)
            connection.close()

            row = index_record(502)
            responses = [index_response([row], page_size=1, total=3),
                         index_response([row], page_size=1, total=3),
                         index_response([row], page_size=1, total=3)]
            requested_pages = []

            def make_client(*_args, **_kwargs):
                client = Mock()
                client.get.side_effect = lambda _url, params: (
                    requested_pages.append(params["_nPage"]) or responses.pop(0))
                context = MagicMock()
                context.__enter__.return_value = client
                context.__exit__.return_value = False
                return context

            common = ["--game", "19567", "--max-pages", "1", "--per-page", "2",
                      "--limit", "1"]
            run_output = io.StringIO()
            with patch.object(backfill_previews, "ROOT", project), \
                    patch.object(backfill_previews.httpx, "Client", side_effect=make_client), \
                    redirect_stdout(run_output):
                self.assertEqual(main(common + ["--dry-run"]), 0, run_output.getvalue())
                checkpoint_path = project / "logs" / "preview_backfill" / "game_19567_checkpoint.json"
                self.assertFalse(checkpoint_path.exists())
                self.assertEqual(main(common + ["--apply"]), 0)
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                self.assertEqual(checkpoint["next_page"], 2)
                self.assertFalse(checkpoint["pending_apply"])
                self.assertEqual(main(common + ["--resume", "--apply"]), 0)

            self.assertEqual(requested_pages, [1, 1, 2])
            readonly = open_existing_database(database)
            try:
                previews = json.loads(readonly.execute(
                    "SELECT preview_urls_json FROM mods WHERE item_id=502").fetchone()[0])
            finally:
                readonly.close()
            self.assertEqual(previews[0]["image_url"],
                             "https://images.gamebanana.com/img/ss/mods/502.jpg")

    def test_failed_apply_keeps_checkpoint_page_for_retry(self):
        import backfill_previews

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            project = Path(directory)
            database = project / "data" / "eryoutoolbox.db"
            initialize_database(database)
            connection = connect_database(database)
            fixture = mod(item_id=503, previews=[])
            fixture.update(game_id=19567, game_name="Zenless Zone Zero")
            import_samples(connection, [({"path": "fixture", "captured_at":
                            datetime(2026, 10, 1, tzinfo=timezone.utc)}, [fixture])], dry_run=False)
            connection.close()
            checkpoint_path = project / "logs" / "preview_backfill" / "game_19567_checkpoint.json"
            original = {"format": "eryoutoolbox-preview-backfill-v1", "game_id": 19567,
                        "next_page": 7, "exhausted": False, "pending_apply": False}
            save_checkpoint(checkpoint_path, original)
            before = checkpoint_path.read_bytes()

            writable = connect_database(database)
            writable.execute("""
                CREATE TRIGGER fail_preview_update BEFORE UPDATE OF preview_urls_json ON mods
                WHEN OLD.item_id = 503
                BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END
            """)
            writable.commit()
            writable.close()

            client = Mock()
            client.get.return_value = index_response([index_record(503)], page_size=1, total=10)
            context = MagicMock()
            context.__enter__.return_value = client
            context.__exit__.return_value = False
            run_output = io.StringIO()
            with patch.object(backfill_previews, "ROOT", project), \
                    patch.object(backfill_previews.httpx, "Client", return_value=context), \
                    redirect_stdout(run_output):
                status = main(["--game", "19567", "--max-pages", "1", "--per-page", "2",
                               "--limit", "1", "--resume", "--apply"])

            self.assertEqual(status, 1)
            self.assertEqual(client.get.call_args.kwargs["params"]["_nPage"], 7)
            self.assertEqual(checkpoint_path.read_bytes(), before, run_output.getvalue())
            self.assertEqual(len(list((project / "data" / "backups").glob("*.db"))), 1)
            readonly = open_existing_database(database)
            try:
                previews = readonly.execute(
                    "SELECT preview_urls_json FROM mods WHERE item_id=503").fetchone()[0]
            finally:
                readonly.close()
            self.assertEqual(previews, "[]")

    def test_legacy_dry_run_checkpoint_requires_explicit_resume_apply(self):
        import backfill_previews

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            project = Path(directory)
            database = project / "data" / "eryoutoolbox.db"
            initialize_database(database)
            checkpoint_path = project / "logs" / "preview_backfill" / "game_19567_checkpoint.json"
            legacy = {"format": "eryoutoolbox-preview-backfill-v1", "game_id": 19567,
                      "next_page": 9, "apply_next_page": 8, "pending_apply": True,
                      "exhausted": False}
            save_checkpoint(checkpoint_path, legacy)
            before = checkpoint_path.read_bytes()
            args = ["--game", "19567", "--max-pages", "1", "--per-page", "2", "--limit", "1", "--apply"]
            with patch.object(backfill_previews, "ROOT", project), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main(args)
            self.assertEqual(checkpoint_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
