from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_coverage.py"
SPEC = importlib.util.spec_from_file_location("audit_coverage", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit)


def rec(item_id, page, timestamp, field="_tsDateAdded", updated=None):
    return {"item_id": item_id, "page": page, field: timestamp, "_tsDateUpdated": updated}


class CoverageAuditTests(unittest.TestCase):
    def test_descending_time_order_and_boundary_crossing(self):
        cutoff = 1_000
        records = [
            {"item_id": 1, "page": 1, "_tsDateAdded": 1200, "_tsDateUpdated": 1200},
            {"item_id": 2, "page": 1, "_tsDateAdded": 100, "_tsDateUpdated": 1100},
        ]
        result = audit.analyze_channel(records, [{"page": 1, "http_status": 200}], "Generic_Newest", "_tsDateAdded", cutoff, [], max_pages=3)
        self.assertTrue(result["time_order_descending_in_sample"])
        self.assertTrue(result["crossed_30_day_boundary_in_sample"])
        self.assertEqual(result["coverage_status"], "boundary_observed_but_unproven")
        self.assertEqual(result["old_created_recently_updated_item_ids"], [2])

    def test_missing_key_time_makes_order_inconclusive(self):
        result = audit.analyze_channel([rec(1, 1, 100), rec(2, 1, None)], [{"page": 1}],
                                       "Generic_Newest", "_tsDateAdded", 50, [], max_pages=3)
        self.assertEqual(result["missing_key_time_ids"], [2])
        self.assertEqual(result["time_order_status"], "inconclusive")

    def test_cross_page_duplicate_is_detected(self):
        records = [rec(4, 1, 300), rec(5, 1, 200), rec(4, 2, 100)]
        result = audit.duplicate_summary(records)
        self.assertEqual(result["cross_page_duplicate_count"], 1)
        self.assertEqual(result["cross_page_overlaps"]["1:2"], [4])

    def test_page_cap_is_incomplete_even_when_boundary_seen(self):
        records = [rec(1, 1, 200), rec(2, 2, 100)]
        pages = [{"page": 1}, {"page": 2}, {"page": 3}]
        result = audit.analyze_channel(records, pages, "Generic_Newest", "_tsDateAdded", 150, [], max_pages=3)
        self.assertTrue(result["page_limit_reached"])
        self.assertEqual(result["coverage_status"], "incomplete")

    def test_ascending_inversion_is_reported(self):
        result = audit.analyze_channel([rec(1, 1, 100), rec(2, 1, 200)], [{"page": 1}],
                                       "Generic_Newest", "_tsDateAdded", 50, [], max_pages=3)
        self.assertEqual(result["time_order_status"], "sample_inversion")
        self.assertEqual(len(result["ordering_inversions"]), 1)

    def test_modified_timestamp_is_not_used_for_updated_sort(self):
        cutoff = 1_000
        records = [
            {"item_id": 1, "page": 1, "_tsDateAdded": 100, "_tsDateModified": 2000, "_tsDateUpdated": 900},
            {"item_id": 2, "page": 1, "_tsDateAdded": 100, "_tsDateModified": 3000, "_tsDateUpdated": 1100},
        ]
        result = audit.analyze_channel(records, [{"page": 1}], "Generic_LatestUpdated", "_tsDateUpdated", cutoff, [], max_pages=3)
        self.assertTrue(result["crossed_30_day_boundary_in_sample"])
        self.assertEqual(result["time_field"], "_tsDateUpdated")


if __name__ == "__main__":
    unittest.main()


