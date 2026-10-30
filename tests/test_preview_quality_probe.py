from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from eryoutoolbox.database import connect_database, initialize_database  # noqa: E402
from eryoutoolbox.importer import import_samples  # noqa: E402
import probe_preview_quality  # noqa: E402


class PreviewQualityProbeTests(unittest.TestCase):
    def test_probe_is_single_request_dry_run_and_does_not_write_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.db"
            initialize_database(database)
            connection = connect_database(database)
            record = {
                "source": "gamebanana", "item_type": "Mod", "item_id": 732438,
                "game_id": 8552, "game_name": "Genshin Impact", "title": "Sample",
                "original_url": "https://gamebanana.com/mods/732438", "author_id": 7,
                "author_name": "Author", "author_url": "https://gamebanana.com/members/7",
                "tags": [], "preview_urls": [
                    "https://images.gamebanana.com/img/ss/mods/530-90_first.jpg"],
                "content_rating_status": "UNKNOWN",
            }
            imported = import_samples(
                connection,
                [({"path": "fixture", "captured_at": datetime.now(timezone.utc)}, [record])],
                dry_run=False,
            )
            self.assertEqual(imported["inserted"], 1)
            connection.close()
            probe_preview_quality.DATABASE_PATH = database

            images = [{
                "_sFile": f"original-{i}.jpg",
                "_sFile100": f"100-90_thumb-{i}.jpg",
                "_sFile530": f"530-90_card-{i}.jpg",
            } for i in range(6)]
            response = Mock(status_code=200)
            response.raise_for_status.return_value = None
            response.json.return_value = {"_aPreviewMedia": {
                "_sBaseUrl": "https://images.gamebanana.com/img/ss/mods",
                "_aImages": images,
            }}
            before = hashlib.sha256(database.read_bytes()).digest()
            output = io.StringIO()
            with patch.object(probe_preview_quality.httpx, "get", return_value=response) as get:
                with redirect_stdout(output):
                    status = probe_preview_quality.inspect_mod()
            after = hashlib.sha256(database.read_bytes()).digest()

            self.assertEqual(status, 0)
            self.assertEqual(get.call_count, 1)
            self.assertIn("Valid original URLs: 6", output.getvalue())
            self.assertIn("Dry-run only", output.getvalue())
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
