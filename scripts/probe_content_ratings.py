"""Small public rating audit; saves only rating fields, never descriptions or media."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import sqlite3
import sys
import json
from pathlib import Path
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]

def rating_fields(value):
    if not isinstance(value, dict):
        return {}
    return {key: val for key, val in value.items()
            if "rating" in key.lower() or "visibility" in key.lower()}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--item-id', type=int, action='append', default=[])
    args = parser.parse_args()
    if len(args.item_id) > 18 or any(i < 1 for i in args.item_id):
        parser.error('Use at most 18 positive MOD IDs.')
    connection = sqlite3.connect((ROOT / 'data' / 'eryoutoolbox.db').as_uri() + '?mode=ro', uri=True)
    sys.path.insert(0, str(ROOT / 'src'))
    from eryoutoolbox.content_ratings import source_ratings
    rows = connection.execute("SELECT item_id,raw_metadata_json FROM mods WHERE source='gamebanana' AND item_type='Mod' ORDER BY item_id DESC").fetchall()
    connection.close()
    saved = {i: source_ratings(raw) for i, raw in rows}
    counts = Counter(code for value in saved.values() for code in value['codes'])
    candidates = args.item_id or [i for i, raw in rows if json.loads(raw or '{}').get('_record', {}).get('has_content_ratings') is True][:6]
    report = {'format': 'eryoutoolbox-rating-audit-v1', 'observed_at': datetime.now(timezone.utc).isoformat(),
              'local_total': len(rows), 'local_counts': dict(counts), 'samples': [], 'errors': []}
    try:
        with httpx.Client(timeout=20) as client:
            def get(url, **kwargs):
                time.sleep(1)
                response = client.get(url, **kwargs)
                response.raise_for_status()
                return response.json()
            config = get("https://gamebanana.com/apiv11/Mod/ListFilterConfig")
            report["filter"] = next(f for f in config["_aFilters"] if f["_sAlias"] == "Generic_ContentRatings")
            rows = get("https://gamebanana.com/apiv11/Mod/Index", params={"_nPerpage": 2, "_nPage": 1, "_aFilters[Generic_Game]": 19567})["_aRecords"]
            indexed = {row['_idRow']: row for row in rows}
            for item_id in dict.fromkeys(candidates + list(indexed)):
                sample = {'source': 'gamebanana', 'item_type': 'Mod', 'item_id': item_id,
                          'list': rating_fields(indexed.get(item_id)), 'saved': saved.get(item_id)}
                detail = get(f"https://gamebanana.com/apiv11/Mod/{item_id}/ProfilePage")
                if detail.get('_idRow') != item_id:
                    raise ValueError(f'Unexpected detail identity for {item_id}')
                sample['detail'] = rating_fields(detail)
                sample['http_status'] = 200
                sample['parsed'] = source_ratings(sample['detail'])
                report['samples'].append(sample)
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    path = ROOT / "logs" / ("content_ratings_step04b_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + ".json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print("Report:", path)
    return bool(report["errors"])

if __name__ == "__main__":
    raise SystemExit(main())
