"""Real HTTP read-state rehearsal on an official SQLite backup copy only."""
from datetime import datetime, timezone
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from queue import Queue
import sqlite3
import subprocess
import sys
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from eryoutoolbox.ui_queries import readonly_connection
from eryoutoolbox.subscriptions import migrate
from react_api import ReadOnlyAPI, make_handler
from backup_project import sqlite_copy, checkpoint_paths
from verify_backup import sha256_file

TABLES = ('mods', 'user_states', 'mod_events', 'sync_runs', 'author_subscriptions')

def summary(database):
    c = readonly_connection(database)
    try:
        counts = {}; hashes = {}
        for table in TABLES:
            rows = c.execute(f'SELECT * FROM "{table}" ORDER BY 1,2,3').fetchall()
            counts[table] = len(rows)
            hashes[table] = hashlib.sha256(json.dumps([tuple(r) for r in rows], ensure_ascii=True).encode()).hexdigest()
        return {'schema': c.execute('PRAGMA user_version').fetchone()[0], 'counts': counts,
                'hashes': hashes, 'integrity': c.execute('PRAGMA integrity_check').fetchone()[0],
                'foreign_keys': len(c.execute('PRAGMA foreign_key_check').fetchall())}
    finally:
        c.close()

def serve_copy(database):
    database = Path(database).resolve()
    if not database.is_relative_to(ROOT / 'data' / 'diagnostics') or database.name != 'working.db':
        raise ValueError('Test server accepts only the diagnostic working.db copy')
    api = ReadOnlyAPI(database)
    with ThreadingHTTPServer(('127.0.0.1', 0), make_handler(api, 8766)) as server:
        server.RequestHandlerClass = make_handler(api, server.server_port)
        print(json.dumps({'port': server.server_port}), flush=True)
        server.serve_forever()

def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    directory = ROOT / 'data' / 'diagnostics' / f'read_state_{stamp}'
    directory.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'data' / 'eryoutoolbox.db'
    pristine = directory / 'before.db'; working = directory / 'working.db'
    before_hash = sha256_file(source)
    checkpoints = {p: sha256_file(p) for p in checkpoint_paths(ROOT)}
    report = {'test_database': str(working), 'production_database': str(source),
              'started_at': datetime.now(timezone.utc).isoformat(), 'steps': [], 'passed': False}
    process = None; error_log = None
    def stop():
        nonlocal process, error_log
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            process.stdout.close(); process = None
        if error_log is not None: error_log.close(); error_log = None
    def start():
        nonlocal process, error_log
        error_log = (directory / 'api.log').open('a', encoding='utf-8')
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve-copy', str(working)],
            stdout=subprocess.PIPE, stderr=error_log, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        queue = Queue()
        Thread(target=lambda: queue.put(process.stdout.readline()), daemon=True).start()
        return json.loads(queue.get(timeout=15))['port'], process.pid
    def request(port, method, path, body=None):
        c = HTTPConnection('127.0.0.1', port, timeout=15)
        try:
            c.request(method, path, json.dumps(body) if body is not None else None,
                      {'Origin': f'http://127.0.0.1:{port}', 'Content-Type': 'application/json', 'X-ErYouToolbox': '1'})
            r = c.getresponse(); data = json.loads(r.read())
            if r.status != 200: raise RuntimeError(f'HTTP {r.status}: {data}')
            return data
        finally: c.close()
    try:
        for src, dst in ((source, pristine), (pristine, working)):
            c = readonly_connection(src); target = sqlite3.connect(dst)
            try: sqlite_copy(c, target)
            finally: target.close(); c.close()
        report['before'] = summary(pristine)
        migrate(working)
        report['migrated'] = summary(working)
        backups_before_repeat = list((directory / 'backups').glob('*.db'))
        migrate(working)
        assert len(list((directory / 'backups').glob('*.db'))) == len(backups_before_repeat)
        c = readonly_connection(working)
        try: source_name, item_id = tuple(c.execute("SELECT source,item_id FROM mods WHERE item_type='Mod' ORDER BY source,item_id LIMIT 1").fetchone())
        finally: c.close()
        from urllib.parse import urlencode
        path = '/api/read-state?' + urlencode({'source': source_name, 'item_id': item_id})
        port, first_pid = start()
        report['api_processes'] = [first_pid]
        for flag in (True, False, True):
            data = request(port, 'POST', '/api/read-state', {'source': source_name, 'item_id': item_id, 'is_read': flag})
            queried = request(port, 'GET', path)
            assert data['is_read'] == queried['is_read'] == flag
            report['steps'].append({'operation': 'mark_read' if flag else 'mark_unread', 'http_status': 200,
                                    'queried_state': queried, 'api_pid': first_pid})
        first_time = queried['first_viewed_at']
        stop(); port, second_pid = start(); report['api_processes'].append(second_pid)
        persisted = request(port, 'GET', path)
        assert persisted['is_read'] and persisted['first_viewed_at'] == first_time
        backup_count = len(list((directory / 'backups').glob('*.db')))
        request(port, 'POST', '/api/read-state', {'source': source_name, 'item_id': item_id, 'is_read': True})
        assert backup_count == len(list((directory / 'backups').glob('*.db')))
        report['steps'].append({'operation': 'restart_api_and_query', 'http_status': 200, 'queried_state': persisted, 'api_pid': second_pid})
        page = request(port, 'GET', '/api/mods?' + urlencode({'search': str(item_id), 'read': 'read'}))
        assert any(i['source'] == source_name and i['item_id'] == item_id and i['is_read'] for i in page['items'])
        stop()
        after = summary(working); report['after'] = after
        assert after['integrity'] == 'ok' and after['foreign_keys'] == 0
        for table in ('mods', 'mod_events', 'sync_runs', 'author_subscriptions'):
            assert after['hashes'][table] == report['before']['hashes'][table]
        old = readonly_connection(pristine); new = readonly_connection(working)
        try:
            fields = [r[1] for r in old.execute('PRAGMA table_info(user_states)') if r[1] not in ('is_read', 'updated_at')]
            columns = ','.join('"' + field + '"' for field in fields)
            assert [tuple(r) for r in old.execute(f'SELECT {columns} FROM user_states ORDER BY 1,2,3')] == [tuple(r) for r in new.execute(f'SELECT {columns} FROM user_states ORDER BY 1,2,3')]
        finally: old.close(); new.close()
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        stop()
        report['production_unchanged'] = before_hash == sha256_file(source)
        report['checkpoints_unchanged'] = all(path.exists() and sha256_file(path) == digest for path, digest in checkpoints.items())
        report['passed'] = report['passed'] and report['production_unchanged'] and report['checkpoints_unchanged']
        path = directory / 'report.json'
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=True, indent=2)); print('Report:', path)
    return int(not report['passed'])

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--serve-copy': serve_copy(sys.argv[2])
    else: raise SystemExit(main())
