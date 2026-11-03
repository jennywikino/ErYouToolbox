"""Run a finite sequence of existing rating backfill batches. Default: one dry-run."""
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import math
import time

import httpx

from backfill_content_ratings import (
    ROOT, HEADERS, TIMEOUT, instance_lock, inventory, project_path, read_checkpoint, run,
)
from eryoutoolbox.database import backup_database


def now():
    return datetime.now(timezone.utc).isoformat()


def errors_for(batch, number):
    errors = []
    for item_id, failure in batch.get('failures', {}).items():
        status = failure.get('http_status')
        kind = failure.get('error_type') or (f'HTTP{status}' if status in (403, 429) else 'UnverifiedResponse')
        errors.append({'mod_id': int(item_id), 'error_type': kind, 'http_status': status,
                       'batch': number, 'failed_at': failure.get('failed_at', now()),
                       'retryable': kind != 'KeyboardInterrupt',
                       'retry_after': failure.get('retry_after'),
                       'retry_after_seconds': failure.get('retry_after_seconds'),
                       'reason': failure.get('reason')})
    if batch.get('error'):
        for item_id in batch.get('selected_ids') or [None]:
            errors.append({'mod_id': item_id, 'error_type': batch.get('error_type', 'BatchError'),
                           'http_status': None, 'batch': number, 'failed_at': now(),
                           'retryable': batch.get('error_type') != 'KeyboardInterrupt',
                           'retry_after': None, 'reason': batch['error']})
    return errors


def schedule(database, checkpoint, *, client, backup_factory, apply=False,
             batches=3, limit=20, interval=2.0, game=None, retry_failed=False,
             lock_path=None, on_batch=None, require_resume=False):
    if not 1 <= batches <= 5 or not 1 <= limit <= 20 or interval < 2 or not math.isfinite(interval):
        raise ValueError('Use 1..5 batches, 1..20 MODs per batch, and interval >= 2 seconds')
    result = {'format': 'eryoutoolbox-rating-schedule-v1', 'started_at': now(),
              'mode': 'apply' if apply else 'dry-run', 'planned_batches': batches if apply else 1,
              'limit': limit, 'interval': interval, 'game': game, 'batches': [], 'errors': [],
              'status': 'success', 'checkpoint': str(checkpoint)}
    active_number = 1
    lock_path = lock_path or ROOT / 'logs' / 'content_ratings' / 'instance.lock'
    pause_path = lock_path.parent / 'source_pause.json'
    try:
        with instance_lock(lock_path):
            if pause_path.exists():
                pause = json.loads(pause_path.read_text(encoding='utf-8'))
                if pause.get('format') != 'eryoutoolbox-rating-pause-v1':
                    raise ValueError('Unrecognized source pause record')
                result['not_before'] = pause['not_before']
                if datetime.fromisoformat(pause['not_before']) > datetime.now(timezone.utc):
                    raise ValueError(f"Source Retry-After active until {pause['not_before']}")
            # An old CLI version may still own its per-checkpoint lock.
            if checkpoint.with_suffix('.lock').exists():
                raise RuntimeError('Legacy checkpoint lock exists; inspect the active backfill before retrying')
            if require_resume or retry_failed:
                read_checkpoint(checkpoint, game, required=True)
            result['before'] = {k:v for k,v in inventory(database, game).items() if k != 'eligible_ids'}
            for number in range(1, result['planned_batches'] + 1):
                active_number = number
                if number > 1:
                    time.sleep(interval)
                batch_backup = []
                def backup():
                    batch_backup.append(str(backup_factory(number)))
                batch = run(database, checkpoint, game=game, limit=limit, apply=apply,
                            resume=checkpoint.exists(), retry_failed=retry_failed, client=client,
                            backup=backup, delay=interval)
                batch['batch_number'] = number
                batch['backup'] = batch_backup[0] if batch_backup else None
                saved = batch.get('save', {})
                batch['counts'] = {'requests': batch.get('requests', 0), 'success': len(batch.get('samples', [])),
                    'candidates': saved.get('candidates', 0),
                    'updated': saved.get('updated', 0), 'skipped': saved.get('skipped', 0) + saved.get('unchanged', 0),
                    'failed': len(batch.get('failures', {})) or int(bool(batch.get('error'))),
                    'remaining_unknown': inventory(database, game)['missing']}
                result['batches'].append(batch)
                result['errors'].extend(errors_for(batch, number))
                waits = [(e.get('retry_after_seconds') if e.get('retry_after_seconds') is not None else 21600) for e in result['errors']
                         if e.get('http_status') in (403,429)]
                if waits:
                    # Operational rate-limit report, not a committed scan position.
                    # Protects manual restarts even when no DB rows were committed.
                    deadline = (datetime.now(timezone.utc) + timedelta(seconds=max(waits))).isoformat()
                    pause = {'format': 'eryoutoolbox-rating-pause-v1', 'not_before': deadline}
                    temp = pause_path.with_suffix('.tmp')
                    temp.write_text(json.dumps(pause), encoding='utf-8')
                    temp.replace(pause_path)
                    result['not_before'] = deadline
                if on_batch:
                    on_batch(batch, result['planned_batches'])
                if batch['status'] != 'success':
                    result['status'] = batch['status']
                    if batch['status'] == 'failed' and any(b.get('save', {}).get('updated') for b in result['batches']):
                        result['status'] = 'partial'
                    break
                if not batch.get('selected_ids'):
                    result['stop_reason'] = 'No eligible candidates in this queue'
                    break
    except KeyboardInterrupt:
        result.update(status='stopped', stop_reason='Ctrl+C; current batch checkpoint not advanced')
        result['errors'].append({'mod_id': None, 'error_type': 'KeyboardInterrupt', 'http_status': None,
                                 'batch': active_number, 'failed_at': now(), 'retryable': False,
                                 'retry_after': None, 'reason': 'User stopped scheduler'})
    except Exception as exc:
        result['status'] = 'partial' if any(b.get('save', {}).get('updated') for b in result['batches']) else 'failed'
        result['errors'].append({'mod_id': None, 'error_type': type(exc).__name__, 'http_status': None,
                                 'batch': active_number, 'failed_at': now(), 'retryable': True,
                                 'retry_after': None, 'reason': str(exc)})
    result['finished_at'] = now()
    result['totals'] = {key: sum(b['counts'][key] for b in result['batches'])
                        for key in ('requests', 'success', 'candidates', 'updated', 'skipped', 'failed')}
    # Read progress only; never reconstruct or replace a checkpoint here.
    try:
        progress = read_checkpoint(checkpoint, game)
        result['pending_failures'] = progress['failures']
        deadlines = [value for value in (result.get('not_before'), progress.get('not_before')) if value]
        result['not_before'] = max(deadlines, key=datetime.fromisoformat) if deadlines else None
    except (OSError, ValueError) as exc:
        result['progress_read_error'] = str(exc)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batches', type=int, default=3)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--interval', type=float, default=2)
    parser.add_argument('--game', type=int)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--resume', action='store_true', help='Require an existing checkpoint; otherwise resume automatically when present')
    parser.add_argument('--retry-failed', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.batches <= 5 or not 1 <= args.limit <= 20 or not math.isfinite(args.interval) or args.interval < 2:
        parser.error('Use 1..5 batches, 1..20 MODs per batch, and interval >= 2 seconds')
    games = json.loads((ROOT / 'config' / 'games.json').read_text(encoding='utf-8'))['games']
    if args.game is not None and args.game not in {game['game_id'] for game in games}:
        parser.error('Unknown configured game ID')
    checkpoint = project_path(args.checkpoint or Path('logs/content_ratings') / f'checkpoint_{args.game or "all"}.json')
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    def backup(number):
        path = ROOT / 'data' / 'backups' / f'ratings_schedule_{stamp}_{number}.db'
        if path.exists():
            raise FileExistsError(path)
        backup_database(ROOT / 'data' / 'eryoutoolbox.db', path)
        return path
    def display(batch, total):
        print(f"Batch {batch['batch_number']}/{total}: {json.dumps(batch['counts'])}", flush=True)
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
        result = schedule(ROOT / 'data' / 'eryoutoolbox.db', checkpoint, client=client,
                          backup_factory=backup, apply=args.apply, batches=args.batches,
                          limit=args.limit, interval=args.interval, game=args.game,
                          retry_failed=args.retry_failed, on_batch=display, require_resume=args.resume)
    # PowerShell invocation always uses the project's local virtual environment.
    relative = checkpoint.relative_to(ROOT).as_posix().replace("'", "''")
    continuation = f"& $python scripts/run_rating_backfill.py --checkpoint '{relative}' --limit {args.limit} --batches {args.batches} --interval {args.interval:g}"
    if args.game:
        continuation += f' --game {args.game}'
    if checkpoint.exists():
        continuation += ' --resume'
    if args.retry_failed:
        continuation += ' --retry-failed'
    result['next_command'] = continuation + (' --apply' if args.apply else ' --dry-run')
    path = ROOT / 'logs' / 'content_ratings' / f'schedule_{stamp}.json'
    with path.open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({'status': result['status'], 'totals': result['totals'], 'report': str(path),
                      'classification_before': result.get('before'),
                      'not_before': result.get('not_before'), 'next_command': result['next_command']}, ensure_ascii=False))
    return 130 if result['status'] == 'stopped' else int(result['status'] in ('partial', 'failed'))


if __name__ == '__main__':
    raise SystemExit(main())
