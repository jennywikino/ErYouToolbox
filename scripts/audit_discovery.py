"""Read-only discovery audit; two public requests, at most three MOD samples."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from eryoutoolbox.ui_queries import readonly_connection
from eryoutoolbox.gamebanana import TIMEOUT, HEADERS

def main():
    report = {'at': datetime.now(timezone.utc).isoformat(), 'requests': 0, 'errors': []}
    c = readonly_connection(ROOT / 'data' / 'eryoutoolbox.db')
    try:
        row = c.execute('SELECT COUNT(*),COUNT(created_at),COUNT(updated_at),COUNT(author_id) FROM mods').fetchone()
        report['local'] = dict(zip(('total', 'created_at', 'updated_at', 'author_id'), row))
        report['events'] = dict(c.execute('SELECT event_type,COUNT(*) FROM mod_events GROUP BY event_type').fetchall())
        report['tables'] = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        report['last_run'] = dict(c.execute('SELECT * FROM sync_runs ORDER BY started_at DESC,run_id DESC LIMIT 1').fetchone() or {})
        heat = Counter()
        for row in c.execute('SELECT raw_metadata_json FROM mods'):
            data = json.loads(row[0] or '{}')
            record = data.get('_record', data)
            heat.update(k for k in record if any(term in k.lower() for term in ('likecount','viewcount','downloadcount')))
        report['local_heat_fields'] = dict(heat)
    finally:
        c.close()
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            report['requests'] += 1
            response = client.get('https://gamebanana.com/apiv11/Mod/ListFilterConfig')
            response.raise_for_status()
            report['official_sorts'] = response.json()['_aSorts']
            time.sleep(2)
            report['requests'] += 1
            response = client.get('https://gamebanana.com/apiv11/Mod/Index', params={
                '_nPage': 1, '_nPerpage': 3, '_aFilters[Generic_Game]': 8552, '_sSort': 'Generic_MostLiked'})
            report['sample_status'] = response.status_code
            response.raise_for_status()
            rows = response.json()['_aRecords']
            report['samples'] = [{ 'item_id': row.get('_idRow'), 'game_id': row.get('_aGame', {}).get('_idRow'),
                                  'counters': {k:v for k,v in row.items() if any(term in k.lower() for term in ('likecount','viewcount','downloadcount'))}}
                                 for row in rows[:3]]
            report['game_filter_sample_verified'] = bool(rows) and all(row.get('_aGame', {}).get('_idRow') == 8552 for row in rows)
    except Exception as exc:
        report['errors'].append(f'{type(exc).__name__}: {exc}')
    path = ROOT / 'logs' / ('discovery_audit_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '.json')
    path.parent.mkdir(exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print('Report:', path)
    return int(bool(report['errors']))

if __name__ == '__main__':
    raise SystemExit(main())
