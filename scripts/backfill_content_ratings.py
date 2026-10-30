"""Bounded source-rating enrichment. Dry-run never changes DB/checkpoint."""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from eryoutoolbox.content_ratings import source_ratings, save_verified_samples
from eryoutoolbox.database import backup_database
from eryoutoolbox.gamebanana import HEADERS, TIMEOUT, _retry_after_seconds
from eryoutoolbox.ui_queries import readonly_connection

FORMAT = 'eryoutoolbox-rating-backfill-v1'
VERIFIED = {'explicit_labels', 'source_unrated_flag'}


@contextmanager
def instance_lock(path):
    """OS-owned lock shared by both entrypoints; released even after process exit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if path.stat().st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another rating backfill instance is active') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def inventory(database, game=None):
    connection = readonly_connection(database)
    try:
        rows = connection.execute("SELECT item_id,raw_metadata_json FROM mods WHERE source='gamebanana' AND item_type='Mod'" +
                                  (' AND game_id=?' if game else '') + ' ORDER BY item_id DESC',
                                  (game,) if game else ()).fetchall()
        codes = Counter()
        states = Counter()
        missing = []
        for row in rows:
            rating = source_ratings(row['raw_metadata_json'])
            codes.update(rating['codes'])
            states.update([rating['verification']])
            if rating['verification'] not in VERIFIED:
                missing.append(row['item_id'])
        return {'total': len(rows), 'codes': dict(codes), 'verification': dict(states),
                'missing': len(missing), 'eligible_ids': missing}
    finally:
        connection.close()


def read_checkpoint(path, game, required=False):
    if not path.exists():
        if required:
            raise ValueError(f'Checkpoint not found: {path}')
        return {'format': FORMAT, 'game': game, 'attempted_ids': [], 'failures': {}}
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or value.get('format') != FORMAT or value.get('game') != game
            or not isinstance(value.get('attempted_ids'), list) or not isinstance(value.get('failures'), dict)
            or any(type(i) is not int or i < 1 for i in value['attempted_ids'])
            or any(not key.isdecimal() or int(key) < 1 for key in value['failures'])):
        raise ValueError('Unrecognized checkpoint or wrong game; file was not changed')
    return value


def select_ids(state, checkpoint, limit, retry_failed=False):
    if not 1 <= limit <= 20:
        raise ValueError('limit must be between 1 and 20')
    attempted = set(checkpoint['attempted_ids'])
    failed = checkpoint['failures']
    return [i for i in state['eligible_ids']
            if (str(i) in failed if retry_failed else i not in attempted)][:limit]


def fetch_batch(client, ids, delay=1.0):
    if len(ids) > 20:
        raise ValueError('At most 20 MODs per batch')
    report = {'format': 'eryoutoolbox-rating-audit-v1',
              'observed_at': datetime.now(timezone.utc).isoformat(),
              'samples': [], 'failures': {}, 'attempted_ids': [], 'requests': 0}
    for item_id in ids:
        if report['requests']:
            try:
                time.sleep(max(1.0, delay))
            except KeyboardInterrupt:
                report['interrupted'] = True
                break
        report['attempted_ids'].append(item_id)
        report['requests'] += 1
        response = None
        try:
            response = client.get(f'https://gamebanana.com/apiv11/Mod/{item_id}/ProfilePage')
            if response.status_code in (403, 429):
                report['failures'][str(item_id)] = {
                    'http_status': response.status_code, 'reason': 'Source blocked/rate-limited; batch stopped',
                    'failed_at': datetime.now(timezone.utc).isoformat(),
                    'retry_after': response.headers.get('Retry-After'),
                    'retry_after_seconds': _retry_after_seconds(response.headers.get('Retry-After'))}
                # Do not issue another request in this run. Retry is an explicit
                # future command, after the saved Retry-After deadline.
                break
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get('_idRow') != item_id:
                raise ValueError('Unexpected detail JSON structure or identity')
            fields = {key: payload[key] for key in ('_aContentRatings', '_bHasContentRatings', '_sInitialVisibility') if key in payload}
            rating = source_ratings(fields)
            if rating['verification'] not in VERIFIED:
                report['failures'][str(item_id)] = {'http_status': 200,
                    'failed_at': datetime.now(timezone.utc).isoformat(),
                    'reason': 'No explicit labels or source Unrated flag; remains UNKNOWN', 'fields': fields}
                continue
            report['samples'].append({'source': 'gamebanana', 'item_type': 'Mod',
                                      'item_id': item_id, 'http_status': 200, 'detail': fields})
        except (httpx.HTTPError, ValueError) as exc:
            report['failures'][str(item_id)] = {'reason': f'{type(exc).__name__}: {exc}',
                'error_type': type(exc).__name__,
                'failed_at': datetime.now(timezone.utc).isoformat(),
                'http_status': exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else
                    getattr(response, 'status_code', None)}
            break
        except KeyboardInterrupt:
            report['interrupted'] = True
            report['failures'][str(item_id)] = {'reason': 'User interrupted request', 'error_type': 'KeyboardInterrupt', 'http_status': None,
                                              'failed_at': datetime.now(timezone.utc).isoformat()}
            break
    return report


def project_path(path):
    path = (ROOT / path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Runtime files must stay inside project root')
    return path


def run(database, checkpoint_path, *, game=None, limit=10, resume=False,
        retry_failed=False, apply=False, client=None, backup=None, delay=1.0):
    state = inventory(database, game)
    checkpoint = read_checkpoint(checkpoint_path, game, required=resume)
    if checkpoint_path.exists() and not resume:
        raise ValueError('Checkpoint exists; use --resume (or another --checkpoint)')
    if retry_failed and not resume:
        raise ValueError('--retry-failed requires --resume')
    if checkpoint.get('not_before'):
        deadline = datetime.fromisoformat(checkpoint['not_before'])
        if deadline > datetime.now(timezone.utc):
            raise ValueError(f'Source Retry-After active until {deadline.isoformat()}')
    selected = select_ids(state, checkpoint, limit, retry_failed)
    report = fetch_batch(client, selected, delay=delay)
    report.update({'mode': 'apply' if apply else 'dry-run', 'game': game,
                   'before': {k: v for k, v in state.items() if k != 'eligible_ids'},
                   'selected_ids': selected, 'checkpoint_updated': False, 'backup': None})
    if report.get('interrupted'):
        report.update(status='stopped', remaining_unverified=state['missing'])
        return report
    connection = None
    try:
        if apply:
            connection = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=rw', uri=True, timeout=5)
            connection.execute('PRAGMA foreign_keys=ON')
        else:
            connection = readonly_connection(database)
        report['save'] = save_verified_samples(connection, report, dry_run=not apply, before_write=backup)
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}', error_type=type(exc).__name__)
        return report
    except KeyboardInterrupt:
        report.update(status='stopped', error='User interrupted database operation', error_type='KeyboardInterrupt')
        return report
    finally:
        if connection is not None:
            connection.close()
    updated_state = inventory(database, game)
    remaining = set(updated_state['eligible_ids'])
    failures = dict(checkpoint['failures'])
    failures.update(report['failures'])
    if apply:
        # Only a committed and readable source rating may clear an earlier failure.
        for sample in report['samples']:
            key = str(sample['item_id'])
            if sample['item_id'] in remaining:
                failures[key] = {'reason': 'Verified sample could not be persisted; retry required'}
                report['failures'][key] = failures[key]
            else:
                failures.pop(key, None)
        failures = {key: value for key, value in failures.items() if int(key) in remaining}
    next_checkpoint = {'format': FORMAT, 'game': game,
                       'attempted_ids': sorted(set(checkpoint['attempted_ids']) | set(report['attempted_ids'])),
                       'failures': failures, 'last_run_at': report['observed_at']}
    from datetime import timedelta
    waits = [value.get('retry_after_seconds') for value in report['failures'].values()]
    waits = [value for value in waits if value is not None]
    if waits:
        next_checkpoint['not_before'] = (datetime.now(timezone.utc) + timedelta(seconds=max(waits))).isoformat()
    report['remaining_unverified'] = updated_state['missing']
    report['next_ids'] = select_ids(updated_state, next_checkpoint, limit)
    report['retry_ids'] = [int(key) for key in failures]
    report['status'] = ('partial' if report['samples'] else 'failed') if report['failures'] else 'success'
    if apply and report['status'] != 'failed':
        # DB has already committed. A checkpoint write failure leaves the old
        # position intact; reruns skip the already verified rows in the DB.
        temp = checkpoint_path.with_suffix('.tmp')
        temp.write_text(json.dumps(next_checkpoint, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(checkpoint_path)
        report['checkpoint_updated'] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--game', type=int)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--checkpoint', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 20:
        parser.error('--limit must be between 1 and 20')
    games = json.loads((ROOT / 'config' / 'games.json').read_text(encoding='utf-8'))['games']
    if args.game is not None and args.game not in {g['game_id'] for g in games}:
        parser.error('Unknown configured Game ID')
    database = ROOT / 'data' / 'eryoutoolbox.db'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    lock = None
    backup_path = None
    report = {'status': 'failed'}
    try:
        checkpoint_path = project_path(args.checkpoint or Path('logs') / 'content_ratings' / f'checkpoint_{args.game or "all"}.json')
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        if args.apply:
            lock = checkpoint_path.with_suffix('.lock')
            # Refuse parallel writers using the same progress file.
            handle = lock.open('x')
            handle.close()
        def backup():
            nonlocal backup_path
            backup_path = ROOT / 'data' / 'backups' / f'ratings_batch_{stamp}.db'
            if backup_path.exists():
                raise FileExistsError(backup_path)
            backup_database(database, backup_path)
        with instance_lock(ROOT / 'logs' / 'content_ratings' / 'instance.lock'), httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            report = run(database, checkpoint_path, game=args.game, limit=args.limit,
                         resume=args.resume, retry_failed=args.retry_failed,
                         apply=args.apply, client=client, backup=backup)
        report['backup'] = str(backup_path) if backup_path else None
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    finally:
        if lock is not None and 'handle' in locals():
            lock.unlink(missing_ok=True)
    path = ROOT / 'logs' / 'content_ratings' / f'run_{stamp}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print('Report:', path)
    return int(report['status'] == 'failed')


if __name__ == '__main__':
    raise SystemExit(main())
