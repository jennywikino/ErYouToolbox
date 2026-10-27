from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from eryoutoolbox.database import backup_database, connect_database, initialize_database  # noqa: E402
from sync import build_parser, load_games, run_all_games, run_sync  # noqa: E402


GAME = {"name": "Genshin Impact", "game_id": 8552}
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def iso(minutes=0):
    return (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def row(item_id=11, title="Sample", updated=1767225600, modified=1767225600, game_id=8552):
    return {
        "_idRow": item_id, "_sModelName": "Mod", "_sName": title,
        "_sProfileUrl": f"https://gamebanana.com/mods/{item_id}",
        "_tsDateAdded": 1767000000, "_tsDateModified": modified,
        "_tsDateUpdated": updated, "_sVersion": "1",
        "_aSubmitter": {"_idRow": 22, "_sName": "Author", "_sProfileUrl": "https://gamebanana.com/members/22"},
        "_aGame": {"_idRow": game_id}, "_aRootCategory": {"_sName": "Characters"},
        "_aSubCategory": {"_sName": "Skins"}, "_aTags": ["skin"],
        "_aPreviewMedia": {}, "_bHasContentRatings": False,
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls = []

    def get(self, url, params):
        sort = params["_sSort"]
        self.calls.append(dict(params))
        queue = self.responses.get(sort, [])
        if not queue:
            raise AssertionError(f"No mock response configured for {sort}")
        return queue.pop(0)


def api_response(records=None, status=200):
    request = httpx.Request("GET", "https://gamebanana.com/apiv11/Mod/Index")
    if status == 200:
        return httpx.Response(status, json={"_aRecords": records or [], "_aMetadata": {}}, request=request)
    return httpx.Response(status, text="temporary failure", request=request)


def success_responses(new_rows, updated_rows=None):
    return {
        "Generic_Newest": [api_response(new_rows)],
        "Generic_LatestUpdated": [api_response(new_rows if updated_rows is None else updated_rows)],
    }


class AllGamesClient:
    def __init__(self, responses=None, same_id=False):
        self.responses = responses or {}
        self.same_id = same_id
        self.calls = []

    def get(self, url, params):
        game_id = params["_aFilters[Generic_Game]"]
        sort = params["_sSort"]
        self.calls.append((game_id, sort))
        queue = self.responses.get((game_id, sort))
        if queue is None:
            item_id = 777 if self.same_id else game_id * 10
            return api_response([row(item_id=item_id, game_id=game_id)])
        value = queue.pop(0)
        return value


def all_games_response_map(game_id, fail_sorts=(), rate_limit=None):
    responses = {}
    for sort in ("Generic_Newest", "Generic_LatestUpdated"):
        if rate_limit == (game_id, sort):
            responses[(game_id, sort)] = [httpx.Response(
                429, headers={"Retry-After": "0"}, request=httpx.Request("GET", "https://gamebanana.com"))]
        elif sort in fail_sorts:
            responses[(game_id, sort)] = [api_response(status=503), api_response(status=503)]
    return responses


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=ROOT)
        self.db_path = Path(self.temp_dir.name) / "sync.db"
        initialize_database(self.db_path)
        self.connection = connect_database(self.db_path)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def count(self, table):
        return self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def run_apply(self, client, minute=0, before_write=None):
        return run_sync(GAME, client, self.connection, max_pages=1, per_page=10,
                        dry_run=False, before_write=before_write,
                        started_at=iso(minute), ended_at=iso(minute))

    def test_two_scans_succeed_and_duplicate_record_is_deduplicated(self):
        client = FakeClient(success_responses([row()]))
        result = run_sync(GAME, client, self.connection, dry_run=True, ended_at=iso())
        self.assertEqual(client.calls[0]["_sSort"], "Generic_Newest")
        self.assertEqual(client.calls[1]["_sSort"], "Generic_LatestUpdated")
        self.assertEqual(result["requests"], 2)
        self.assertEqual(result["fetched"], 2)
        self.assertEqual(result["unique"], 1)
        self.assertEqual(result["coverage"], "incomplete")

    def test_per_page_50_is_accepted_and_limits_are_enforced(self):
        client = FakeClient(success_responses([row()]))
        result = run_sync(GAME, client, self.connection, max_pages=1, per_page=50,
                          dry_run=True, ended_at=iso())
        self.assertEqual(result["requests"], 2)
        self.assertTrue(all(call["_nPerpage"] == 50 for call in client.calls))
        for invalid in (0, 51):
            with self.assertRaisesRegex(ValueError, "1 and 50"):
                run_sync(GAME, FakeClient(success_responses([row()])), self.connection,
                         max_pages=1, per_page=invalid, dry_run=True, ended_at=iso())

    def test_first_sync_inserts_mod_and_first_seen(self):
        result = self.run_apply(FakeClient(success_responses([row()])))
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["new_events"], 1)
        self.assertEqual(self.count("mods"), 1)
        self.assertEqual(self.count("mod_events"), 1)
        self.assertEqual(self.count("sync_runs"), 1)

    def test_second_sync_is_idempotent(self):
        self.run_apply(FakeClient(success_responses([row()])), minute=0)
        result = self.run_apply(FakeClient(success_responses([row()])), minute=0)
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(self.count("mods"), 1)
        self.assertEqual(self.count("mod_events"), 1)

    def test_later_source_timestamp_creates_source_updated(self):
        self.run_apply(FakeClient(success_responses([row(updated=1767225600)])), minute=0)
        result = self.run_apply(FakeClient(success_responses([row(updated=1767312000)])), minute=1)
        self.assertEqual(result["source_update_events"], 1)
        self.assertEqual(self.count("mod_events"), 2)
        self.assertEqual(self.connection.execute("SELECT event_type FROM mod_events ORDER BY event_id DESC").fetchone()[0], "source_updated")

    def test_title_change_without_updated_timestamp_is_metadata_only(self):
        self.run_apply(FakeClient(success_responses([row(updated=None)])), minute=0)
        result = self.run_apply(FakeClient(success_responses([row(title="Changed", updated=None)])), minute=1)
        self.assertEqual(result["metadata_events"], 1)
        self.assertEqual(result["source_update_events"], 0)

    def test_one_scan_failure_yields_partial_and_keeps_successful_rows(self):
        responses = success_responses([row()])
        responses["Generic_LatestUpdated"] = [api_response(status=503), api_response(status=503)]
        client = FakeClient(responses)
        with patch("eryoutoolbox.gamebanana.time.sleep"):
            result = self.run_apply(client)
        self.assertEqual(result["sync_status"], "partial")
        self.assertEqual(self.count("mods"), 1)
        self.assertEqual(result["requests"], 3)

    def test_both_scans_fail_without_mod_or_event_changes(self):
        responses = {"Generic_Newest": [api_response(status=503), api_response(status=503)],
                     "Generic_LatestUpdated": [api_response(status=503), api_response(status=503)]}
        with patch("eryoutoolbox.gamebanana.time.sleep"):
            result = self.run_apply(FakeClient(responses))
        self.assertEqual(result["sync_status"], "failed")
        self.assertEqual(self.count("mods"), 0)
        self.assertEqual(self.count("mod_events"), 0)

    def test_dry_run_writes_neither_database_nor_backup(self):
        calls = []
        result = run_sync(GAME, FakeClient(success_responses([row()])), self.connection,
                          dry_run=True, before_write=lambda: calls.append(True), ended_at=iso())
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(calls, [])
        self.assertEqual((self.count("mods"), self.count("mod_events"), self.count("sync_runs")), (0, 0, 0))

    def test_user_state_is_preserved_during_sync(self):
        self.run_apply(FakeClient(success_responses([row()])), minute=0)
        self.connection.execute("UPDATE user_states SET is_read=1,is_favorite=1,note='keep',workflow_status='to_repost'")
        self.connection.commit()
        self.run_apply(FakeClient(success_responses([row(title="Changed")])), minute=1)
        state = self.connection.execute("SELECT is_read,is_favorite,note,workflow_status FROM user_states").fetchone()
        self.assertEqual(tuple(state), (1, 1, "keep", "to_repost"))

    def test_database_failure_rolls_back_mods_events_and_sync_run(self):
        self.connection.execute("CREATE TRIGGER fail_events BEFORE INSERT ON mod_events BEGIN SELECT RAISE(ABORT, 'forced failure'); END")
        self.connection.commit()
        result = self.run_apply(FakeClient(success_responses([row()])))
        self.assertEqual(result["sync_status"], "failed")
        self.assertIn("Database transaction failed", result["database_error"])
        self.assertEqual((self.count("mods"), self.count("mod_events"), self.count("sync_runs")), (0, 0, 0))

    def test_apply_backup_api_completes_before_sync_transaction(self):
        backup_path = Path(self.temp_dir.name) / "before.db"
        result = self.run_apply(FakeClient(success_responses([row()])),
                                before_write=lambda: backup_database(self.db_path, backup_path))
        self.assertTrue(backup_path.is_file())
        backup = sqlite3.connect(backup_path)
        try:
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM mods").fetchone()[0], 0)
        finally:
            backup.close()
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(self.count("sync_runs"), 1)

    def test_games_config_loads_six_unique_games_and_old_cli_still_parses(self):
        games = load_games()
        self.assertEqual(len(games), 6)
        self.assertEqual(len({game["game_id"] for game in games}), 6)
        args = build_parser().parse_args(["--game", "8552", "--max-pages", "1", "--per-page", "10"])
        self.assertEqual(args.game, 8552)
        self.assertFalse(args.all_games)

    def test_all_six_games_succeed_with_default_twelve_requests(self):
        games = load_games()
        client = AllGamesClient()
        summary = run_all_games(games, client, self.connection, dry_run=True)
        self.assertEqual(summary["games_attempted"], 6)
        self.assertEqual(summary["games_success"], 6)
        self.assertEqual(summary["requests_total"], 12)
        self.assertEqual(summary["overall_status"], "success")
        self.assertTrue(all(item["coverage"] == "incomplete" for item in summary["games"]))

    def test_one_game_failure_does_not_stop_other_games(self):
        games = load_games()
        responses = all_games_response_map(games[1]["game_id"], fail_sorts=("Generic_Newest", "Generic_LatestUpdated"))
        client = AllGamesClient(responses)
        with patch("eryoutoolbox.gamebanana.time.sleep"):
            summary = run_all_games(games, client, self.connection, dry_run=True)
        self.assertEqual(summary["games_failed"], 1)
        self.assertEqual(summary["games_success"], 5)
        self.assertEqual(len(client.calls), 14)

    def test_single_channel_failure_marks_game_partial(self):
        games = load_games()
        responses = all_games_response_map(games[0]["game_id"], fail_sorts=("Generic_LatestUpdated",))
        with patch("eryoutoolbox.gamebanana.time.sleep"):
            summary = run_all_games(games[:1], AllGamesClient(responses), self.connection, dry_run=True)
        self.assertEqual(summary["games_partial"], 1)
        self.assertEqual(summary["games"][0]["status"], "partial")

    def test_429_stops_remaining_games_and_does_not_retry_forever(self):
        games = load_games()
        responses = all_games_response_map(games[0]["game_id"], rate_limit=(games[0]["game_id"], "Generic_Newest"))
        client = AllGamesClient(responses)
        with patch("eryoutoolbox.gamebanana.time.sleep"):
            summary = run_all_games(games, client, self.connection, dry_run=True)
        self.assertEqual(summary["requests_total"], 1)
        self.assertEqual(summary["games_skipped"], 5)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(summary["overall_status"], "partial")

    def test_same_item_id_across_games_is_not_cross_merged(self):
        games = load_games()[:2]
        summary = run_all_games(games, AllGamesClient(same_id=True), self.connection, dry_run=True)
        self.assertEqual(summary["games"][0]["unique"], 1)
        self.assertEqual(summary["games"][1]["unique"], 0)
        self.assertEqual(summary["games"][1]["skipped"], 1)
        self.assertEqual(summary["games"][1]["status"], "partial")

    def test_dry_run_all_games_does_not_write_or_back_up(self):
        calls = []
        summary = run_all_games(load_games(), AllGamesClient(), self.connection,
                                dry_run=True, before_write=lambda: calls.append(True))
        self.assertEqual(calls, [])
        self.assertEqual((self.count("mods"), self.count("mod_events"), self.count("sync_runs")), (0, 0, 0))
        self.assertEqual(summary["coverage"], "incomplete")

    def test_apply_writes_events_backup_and_separate_game_runs(self):
        games = load_games()
        backup_paths = []

        def do_backup():
            path = Path(self.temp_dir.name) / f"before-{len(backup_paths)}.db"
            backup_database(self.db_path, path)
            backup_paths.append(path)

        summary = run_all_games(games, AllGamesClient(), self.connection,
                                dry_run=False, before_write=do_backup)
        self.assertEqual(summary["inserted_total"], 6)
        self.assertEqual(self.count("mods"), 6)
        self.assertEqual(self.count("mod_events"), 6)
        self.assertEqual(self.count("sync_runs"), 6)
        self.assertEqual(len(backup_paths), 6)
        self.assertTrue(all(path.is_file() for path in backup_paths))

    def test_repeat_all_games_sync_is_idempotent(self):
        games = load_games()
        first = run_all_games(games, AllGamesClient(), self.connection, dry_run=False)
        second = run_all_games(games, AllGamesClient(), self.connection, dry_run=False)
        self.assertEqual(first["inserted_total"], 6)
        self.assertEqual(second["inserted_total"], 0)
        self.assertEqual(self.count("mods"), 6)
        self.assertEqual(self.count("mod_events"), 6)
        self.assertEqual(self.count("sync_runs"), 12)


if __name__ == "__main__":
    unittest.main()
