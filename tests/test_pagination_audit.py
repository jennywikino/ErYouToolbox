from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_pagination.py"
SPEC = importlib.util.spec_from_file_location("audit_pagination", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit)


def sample(item_id, added=None, modified=None, updated=None, page=1):
    return {"item_id": item_id, "page": page, "_tsDateAdded": added,
            "_tsDateModified": modified, "_tsDateUpdated": updated}


class PaginationAuditTests(unittest.TestCase):
    def test_cross_page_duplicate_detection(self):
        result = audit.duplicate_analysis([sample(1, page=1), sample(1, page=2), sample(2, page=2)])
        self.assertEqual(result["cross_page_duplicate_count"], 1)
        self.assertEqual(result["cross_page_duplicate_ids"], [1])

    def test_missing_timestamp_and_modified_only(self):
        result = audit.analyze_sort([sample(1, added=100, modified=200), sample(2, added=150)], now_ts=300)
        self.assertEqual(result["missing_updated_count"], 2)
        self.assertEqual(result["modified_without_updated_item_ids"], [1])

    def test_time_ordering_analysis(self):
        records = [sample(1, added=300), sample(2, added=200), sample(3, added=100)]
        result = audit.ordering_analysis(records)
        self.assertEqual(result["_tsDateAdded"]["status"], "sample_descending")
        self.assertEqual(result["_tsDateModified"]["status"], "inconclusive")

    def test_old_creation_recent_explicit_update(self):
        now = 2_000_000
        result = audit.analyze_sort([sample(9, added=now - 60 * 86400, modified=now, updated=now)], now_ts=now)
        self.assertEqual(result["old_created_recent_updated_item_ids"], [9])

    def test_extract_missing_dates_and_metadata(self):
        payload = {"_aRecords": [{"_idRow": 44, "_aGame": {"_idRow": 8552}}],
                   "_aMetadata": {"_bIsComplete": False, "_nRecordCount": 1}}
        rows, metadata_fields, errors = audit.extract_records(payload, "Generic_Newest", 1)
        self.assertIsNone(rows[0]["_tsDateUpdated"])
        self.assertEqual(set(metadata_fields), {"_bIsComplete", "_nRecordCount"})
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
