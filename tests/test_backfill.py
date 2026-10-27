from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from eryoutoolbox.database import connect_database, initialize_database  # noqa: E402
from eryoutoolbox.importer import import_samples  # noqa: E402
from backfill import CHANNELS, run_backfill  # noqa: E402

GAME = {"name": "Genshin Impact", "game_id": 8552}
NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)
CUTOFF = int(NOW.timestamp()) - 30 * 86400


def row(item_id: int, timestamp: int | None, *, updated: int | None = None,
        modified: int | None = None, title: str | None = None) -> dict:
    return {
        "_idRow": item_id, "_sModelName": "Mod", "_sName": title or f"Mod {item_id}",
        "_sProfileUrl": f"https://gamebanana.com/mods/{item_id}",
        "_tsDateAdded": timestamp, "_tsDateModified": modified, "_tsDateUpdated": updated,
        "_aGame": {"_idRow": 8552}, "_aSubmitter": {}, "_aPreviewMedia": {},
    }


def response(records=None, status=200, headers=None):
    request = httpx.Request("GET", "https://gamebanana.com/apiv11/Mod/Index")
    if status == 200:
        return httpx.Response(status, json={"_aRecords": records or [], "_aMetadata": {}}, request=request)
    return httpx.Response(status, text="failure", headers=headers or {}, request=request)


class FakeClient:
    def __init__(self, pages):
        self.pages = {key: list(value) for key, value in pages.items()}
        self.calls = []

    def get(self, url, params):
        key = (params["_sSort"], params["_nPage"])
        self.calls.append(dict(params))
        queue = self.pages.get(key, [])
        if not queue:
            raise AssertionError(f"Unexpected request {key}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def page_map(new_pages, updated_pages=None):
    mapping = {}
    if updated_pages is None:
        updated_pages = [[{**record, "_tsDateUpdated": record.get("_tsDateAdded")} for record in page]
                         for page in new_pages]
    for sort, pages in ((CHANNELS[0][0], new_pages), (CHANNELS[1][0], updated_pages)):
        for page_num, page_rows in enumerate(pages, 1):
            mapping[(sort, page_num)] = [response(page_rows)]
    return mapping


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        initialize_database(self.db_path)
        self.connection = connect_database(self.db_path)

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def run_job(self, client, **kwargs):
        return run_backfill(GAME, client, self.connection, now=NOW, delay=0, **kwargs)

    def test_normal_pagination_and_boundary(self):
        recent, old = int(NOW.timestamp()) - 100, CUTOFF - 10
        client = FakeClient(page_map([[row(1, recent)], [row(2, old)]]))
        result = self.run_job(client, max_pages=5, per_page=10, days=30)
        channel = result["channels"]["Generic_Newest"]
        self.assertEqual(channel["pages_requested"], 2)
        self.assertEqual(channel["coverage_status"], "boundary_observed")
        self.assertEqual(len(client.calls), 4)

    def test_newest_boundary_uses_added_time(self):
        rows = [[row(30, CUTOFF + 1, updated=CUTOFF - 1, modified=CUTOFF - 1),
                 row(3, CUTOFF - 1, updated=int(NOW.timestamp()), modified=int(NOW.timestamp()))]]
        result = self.run_job(FakeClient(page_map(rows)), max_pages=5, per_page=10)
        self.assertEqual(result["channels"]["Generic_Newest"]["boundary_status"], "observed")

    def test_updated_boundary_uses_updated_not_modified(self):
        rows = [[row(4, CUTOFF - 90000, updated=None, modified=int(NOW.timestamp()))]]
        result = self.run_job(FakeClient(page_map(rows + [[]], [[row(4, CUTOFF - 90000, updated=None, modified=int(NOW.timestamp()))], []])), max_pages=2, per_page=10)
        updated = result["channels"]["Generic_LatestUpdated"]
        self.assertEqual(updated["time_field"], "_tsDateUpdated")
        self.assertEqual(updated["boundary_status"], "not_observed")

    def test_missing_timestamp_reported(self):
        result = self.run_job(FakeClient(page_map([[row(5, None)]])), max_pages=1, per_page=10)
        self.assertIn(5, result["channels"]["Generic_Newest"]["missing_timestamp_ids"])
        self.assertEqual(result["channels"]["Generic_Newest"]["coverage_status"], "inconclusive")

    def test_time_order_anomaly_is_inconclusive(self):
        rows = [[row(6, CUTOFF + 10), row(7, CUTOFF + 20)]]
        result = self.run_job(FakeClient(page_map(rows)), max_pages=1, per_page=10)
        self.assertEqual(result["channels"]["Generic_Newest"]["ordering_inversions"], 1)
        self.assertEqual(result["channels"]["Generic_Newest"]["coverage_status"], "inconclusive")

    def test_cross_page_duplicate_detected_and_deduplicated(self):
        rows = [[row(8, CUTOFF + 100)], [row(8, CUTOFF - 100)]]
        result = self.run_job(FakeClient(page_map(rows)), max_pages=2, per_page=10)
        channel = result["channels"]["Generic_Newest"]
        self.assertEqual(channel["duplicate_ids"], [8])
        self.assertEqual(channel["unique_records"], 1)

    def test_page_cap_without_boundary_is_incomplete(self):
        rows = [[row(20 + page_num, CUTOFF + 1000 - page_num)] for page_num in range(2)]
        result = self.run_job(FakeClient(page_map(rows)), max_pages=2, per_page=10)
        channel = result["channels"]["Generic_Newest"]
        self.assertTrue(channel["page_limit_reached"])
        self.assertEqual(channel["coverage_status"], "incomplete")
        self.assertEqual(channel["pages_requested"], 2)

    def test_empty_page_is_reported(self):
        client = FakeClient(page_map([[]]))
        result = self.run_job(client, max_pages=3, per_page=10)
        self.assertTrue(result["channels"]["Generic_Newest"]["empty_page"])
        self.assertEqual(result["channels"]["Generic_Newest"]["pages_requested"], 1)

    def test_api_failure_is_reported_without_unbounded_retry(self):
        failed = response(status=503)
        pages = {("Generic_Newest", 1): [failed, failed],
                 ("Generic_LatestUpdated", 1): [response([row(9, CUTOFF + 10, updated=CUTOFF + 10)])]}
        result = self.run_job(FakeClient(pages), max_pages=1, per_page=10)
        self.assertEqual(result["channels"]["Generic_Newest"]["requests"], 2)
        self.assertEqual(result["overall_status"], "partial")

    def test_old_import_snapshot_does_not_overwrite_newer(self):
        old = row(10, CUTOFF + 1, title="Old")
        new = row(10, CUTOFF + 2, title="New")
        from eryoutoolbox.models import normalize_record
        record_old, record_new = normalize_record(old, GAME), normalize_record(new, GAME)
        import_samples(self.connection, [({"path": "new", "captured_at": NOW}, [record_new])],
                       dry_run=False, now="2026-10-27T00:00:00Z")
        earlier = datetime(2026, 10, 26, tzinfo=timezone.utc)
        import_samples(self.connection, [({"path": "old", "captured_at": earlier}, [record_old])],
                       dry_run=False, now="2026-10-27T00:00:00Z")
        title = self.connection.execute("SELECT title FROM mods WHERE item_id=10").fetchone()[0]
        self.assertEqual(title, "New")

    def test_dry_run_has_no_side_effects(self):
        client = FakeClient(page_map([[row(11, CUTOFF + 1)]]))
        result = self.run_job(client, max_pages=1, per_page=10, dry_run=True)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mods").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mod_events").fetchone()[0], 0)

    def test_apply_is_idempotent_and_emits_first_seen_once(self):
        client1 = FakeClient(page_map([[row(12, CUTOFF + 10)]]))
        first = self.run_job(client1, max_pages=1, per_page=10, dry_run=False)
        client2 = FakeClient(page_map([[row(12, CUTOFF + 10)]]))
        second = self.run_job(client2, max_pages=1, per_page=10, dry_run=False)
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mods").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mod_events WHERE event_type='first_seen'").fetchone()[0], 1)

    def test_boundary_does_not_mean_guaranteed_full_coverage(self):
        rows = [[row(13, CUTOFF + 1), row(14, CUTOFF - 1)]]
        result = self.run_job(FakeClient(page_map(rows)), max_pages=5, per_page=10)
        self.assertEqual(result["coverage"], "boundary_observed")
        self.assertNotEqual(result["coverage"], "complete")

    def test_global_incomplete_when_either_channel_has_not_reached_boundary(self):
        recent = int(NOW.timestamp()) - 100
        new_rows = [[row(21, recent)]]
        updated_rows = [[row(22, recent, updated=recent), row(23, CUTOFF - 1, updated=CUTOFF - 1)]]
        result = self.run_job(FakeClient(page_map(new_rows, updated_rows)),
                              max_pages=1, per_page=10)
        self.assertEqual(result["channels"]["Generic_Newest"]["coverage_status"], "incomplete")
        self.assertEqual(result["channels"]["Generic_LatestUpdated"]["coverage_status"], "boundary_observed")
        self.assertEqual(result["coverage"], "incomplete")

    def test_global_boundary_requires_both_channels(self):
        recent = int(NOW.timestamp()) - 100
        rows = [[row(24, recent), row(25, CUTOFF - 1)]]
        result = self.run_job(FakeClient(page_map(rows)), max_pages=1, per_page=10)
        self.assertEqual(result["coverage"], "boundary_observed")
        self.assertTrue(all(channel["coverage_status"] == "boundary_observed"
                            for channel in result["channels"].values()))

    def test_window_filter_keeps_old_mod_with_recent_source_update_only(self):
        recent = int(NOW.timestamp()) - 100
        old_update = CUTOFF - 1
        old_created_recently_updated = row(26, CUTOFF - 4000000, updated=recent)
        out_of_window = row(27, CUTOFF - 5000000, updated=old_update)
        new_pages = [[old_created_recently_updated, out_of_window], []]
        updated_pages = [[old_created_recently_updated, out_of_window]]
        result = self.run_job(FakeClient(page_map(new_pages, updated_pages)),
                              max_pages=3, per_page=10)
        updated_channel = result["channels"]["Generic_LatestUpdated"]
        self.assertEqual([item["item_id"] for item in updated_channel["records"]], [26])
        self.assertEqual(updated_channel["out_of_window_count"], 1)
        self.assertEqual(updated_channel["pages_requested"], 1)
        self.assertEqual(result["unique_total"], 1)
        self.assertEqual(result["inserted"], 1)

    def test_missing_time_is_not_imported_or_called_complete(self):
        rows = [[row(28, None, updated=None, modified=int(NOW.timestamp()))]]
        result = self.run_job(FakeClient(page_map(rows)), max_pages=1, per_page=10)
        self.assertEqual(result["coverage"], "inconclusive")
        self.assertEqual(result["unique_total"], 0)
        self.assertEqual(result["unknown_timestamp_total"], 2)

    def test_dry_run_does_not_call_backup_or_write(self):
        rows = [[row(29, CUTOFF + 1)]]
        called = []
        result = self.run_job(FakeClient(page_map(rows)), max_pages=1, per_page=10,
                              dry_run=True, before_write=lambda: called.append(True))
        self.assertEqual(called, [])
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mods").fetchone()[0], 0)

    def test_per_page_50_is_allowed_and_out_of_range_values_rejected(self):
        recent = int(NOW.timestamp()) - 100
        records = [row(1000 + index, recent - index) for index in range(50)]
        client = FakeClient(page_map([records]))
        result = self.run_job(client, max_pages=1, per_page=50)
        self.assertEqual(result["fetched_total"], 100)
        self.assertTrue(all(request["_nPerpage"] == 50 for request in client.calls))
        for invalid in (0, 51):
            rejected = FakeClient({})
            with self.assertRaisesRegex(ValueError, "per_page 1..50"):
                self.run_job(rejected, max_pages=1, per_page=invalid)
            self.assertEqual(rejected.calls, [])


if __name__ == "__main__":
    unittest.main()
