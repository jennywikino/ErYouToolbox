"""SQLite Backup API + checkpoint bundle, with isolated restore rehearsal."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
import time
import uuid

from verify_backup import (open_readonly, sha256_file, database_snapshot,
                           integrity_result, foreign_key_violations)

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'eryoutoolbox-project-backup-v1'


def sqlite_copy(source, target, timeout=60):
    deadline = time.monotonic() + timeout
    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise TimeoutError('SQLite backup exceeded the time budget; retry when writers are idle')
    source.backup(target, pages=256, progress=progress, sleep=0.1)


def checkpoint_paths(project, extras=()):
    paths = set((project / 'logs' / 'content_ratings').glob('checkpoint_*.json'))
    paths.update((project / 'logs' / 'preview_backfill').glob('*checkpoint*.json'))
    pause = project / 'logs' / 'content_ratings' / 'source_pause.json'
    if pause.exists():
        paths.add(pause)
    for extra in extras:
        path = (project / extra).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        paths.add(path)
    result = []
    for path in paths:
        path = path.resolve()
        if not path.is_relative_to(project.resolve()):
            raise ValueError('Checkpoint must reside inside project root')
        if path.suffix != '.json':
            raise ValueError('Checkpoint must be JSON')
        result.append(path)
    return sorted(result)


def checkpoint_bytes(path):
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f'Invalid checkpoint object: {path.name}')
    format_name = value.get('format')
    if format_name == 'eryoutoolbox-rating-backfill-v1':
        if (not isinstance(value.get('attempted_ids'), list) or not isinstance(value.get('failures'), dict)
                or any(type(i) is not int or i < 1 for i in value['attempted_ids'])):
            raise ValueError('Invalid rating checkpoint structure')
    elif format_name == 'eryoutoolbox-preview-backfill-v1':
        if type(value.get('next_page')) is not int or value['next_page'] < 1:
            raise ValueError('Invalid preview checkpoint page')
    elif format_name == 'eryoutoolbox-rating-pause-v1':
        timestamp = datetime.fromisoformat(value['not_before'])
        if timestamp.tzinfo is None:
            raise ValueError('Invalid pause timestamp')
    else:
        raise ValueError(f'Unrecognized checkpoint format: {path.name}')
    return raw


def same_volume(project, destination):
    ancestor = destination.resolve()
    while not ancestor.exists():
        ancestor = ancestor.parent
    return os.stat(project).st_dev == os.stat(ancestor).st_dev


def bundle_file(bundle, relative):
    if (not isinstance(relative, str) or Path(relative).is_absolute()
            or PurePosixPath(relative).is_absolute() or '..' in PurePosixPath(relative).parts
            or '\\' in relative or ':' in relative):
        raise ValueError('Unsafe backup manifest path')
    path = (bundle / relative).resolve()
    if not path.is_relative_to(bundle.resolve()) or path == bundle.resolve():
        raise ValueError('Unsafe backup manifest path')
    return path


def verify_bundle(bundle, *, temp_parent, require_complete=True):
    """Restore only into a freshly created temporary directory; never production."""
    bundle = Path(bundle).resolve()
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != FORMAT or (require_complete and manifest.get('status') != 'complete'):
        raise ValueError('Unrecognized or incomplete backup manifest')
    files = manifest['files']
    if not files or files[0]['path'] != 'database.db' or len({f['path'] for f in files}) != len(files):
        raise ValueError('Invalid backup file list')
    for entry in files:
        path = bundle_file(bundle, entry['path'])
        if path.stat().st_size != entry['size'] or sha256_file(path) != entry['sha256']:
            raise ValueError(f"Backup checksum mismatch: {entry['path']}")
        if entry['kind'] == 'checkpoint':
            checkpoint_bytes(path)
    temp_parent = Path(temp_parent)
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='backup_restore_', dir=temp_parent) as directory:
        restored = Path(directory) / 'restored.db'
        source = open_readonly(bundle / 'database.db')
        target = sqlite3.connect(restored)
        try:
            sqlite_copy(source, target)
        finally:
            target.close()
            source.close()
        recovered = open_readonly(restored)
        try:
            snapshot = database_snapshot(recovered)
            integrity = integrity_result(recovered)
            violations = foreign_key_violations(recovered)
        finally:
            recovered.close()
        if integrity != 'ok' or violations or snapshot != manifest['snapshot']:
            raise ValueError('Restored database failed integrity, foreign key or table-count/schema comparison')
        # Also rehearse restoring checkpoints; no original project files are written.
        for entry in files[1:]:
            restored_checkpoint = Path(directory) / entry['path']
            restored_checkpoint.parent.mkdir(parents=True, exist_ok=True)
            restored_checkpoint.write_bytes(bundle_file(bundle, entry['path']).read_bytes())
            checkpoint_bytes(restored_checkpoint)
            if sha256_file(restored_checkpoint) != entry['sha256']:
                raise ValueError('Restored checkpoint checksum mismatch')
    return {'passed': True, 'integrity': integrity, 'foreign_key_violations': len(violations),
            'snapshot': snapshot, 'checkpoints': len(files) - 1}


def create_backup(project, destination, *, extra_checkpoints=(), temp_parent=None):
    project = Path(project).resolve()
    destination = Path(destination).resolve()
    database = project / 'data' / 'eryoutoolbox.db'
    if not database.is_file():
        raise FileNotFoundError(database)
    on_same_volume = same_volume(project, destination)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    bundle = destination / f'eryoutoolbox_{stamp}_{uuid.uuid4().hex[:8]}'
    bundle.mkdir(parents=True, exist_ok=False)
    manifest = {'format': FORMAT, 'status': 'incomplete',
                'created_at': datetime.now(timezone.utc).isoformat(), 'same_project_volume': on_same_volume,
                'files': [], 'source_database': 'data/eryoutoolbox.db',
                'coordination': 'Pause collection/import/backfill before backup; SQLite and JSON are not one atomic transaction.'}
    manifest_path = bundle / 'manifest.json'
    def write_manifest():
        temp = bundle / 'manifest.tmp'
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(manifest_path)
    write_manifest()
    try:
        checkpoints = checkpoint_paths(project, extra_checkpoints)
        checkpoint_data = {path: checkpoint_bytes(path) for path in checkpoints}
        source = open_readonly(database)
        target = sqlite3.connect(bundle / 'database.db')
        try:
            # Pin one SQLite snapshot for counts and Backup API, including WAL.
            source.execute('BEGIN')
            manifest['snapshot'] = database_snapshot(source)
            sqlite_copy(source, target)
        finally:
            target.close()
            source.close()
        for path, raw in checkpoint_data.items():
            relative = Path('checkpoints') / path.relative_to(project)
            saved = bundle / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(raw)
        if checkpoints != checkpoint_paths(project, extra_checkpoints) or any(path.read_bytes() != raw for path, raw in checkpoint_data.items()):
            raise ValueError('Checkpoints changed during backup; stop background writers and retry')
        paths = [('database.db', 'database')] + [(str(Path('checkpoints') / path.relative_to(project)), 'checkpoint') for path in checkpoints]
        for relative, kind in paths:
            path = bundle / relative
            manifest['files'].append({'path': Path(relative).as_posix(), 'kind': kind,
                                      'size': path.stat().st_size, 'sha256': sha256_file(path)})
        write_manifest()
        verification = verify_bundle(bundle, temp_parent=temp_parent or project / 'data', require_complete=False)
        manifest.update(status='complete', verification=verification)
        write_manifest()
        return {'bundle': str(bundle), 'same_project_volume': on_same_volume, **verification}
    except BaseException as exc:
        manifest.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        write_manifest()
        raise


def default_destination(project):
    return Path(project.anchor) / 'ErYouToolboxBackups'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--destination', type=Path, help='Backup root; preferably on another physical disk')
    mode.add_argument('--verify', type=Path, help='Verify/rehearse an existing backup bundle without production restore')
    parser.add_argument('--checkpoint', type=Path, action='append', default=[], help='Additional checkpoint inside project root')
    args = parser.parse_args(argv)
    try:
        if args.verify is None:
            destination = args.destination if args.destination is not None else default_destination(ROOT)
            print(f'Backup destination: {destination}')
            print('NOTICE: Backups on the same physical device cannot protect against loss of that device; use another physical device for disaster recovery.', flush=True)
            if same_volume(ROOT, destination):
                print('WARNING: Target is on the project volume. This is NOT an independent disaster-recovery backup.', flush=True)
            result = create_backup(ROOT, destination, extra_checkpoints=args.checkpoint)
        else:
            result = verify_bundle(args.verify, temp_parent=ROOT / 'data')
        print('Backup verification: PASS')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f'Backup verification: FAIL\n{type(exc).__name__}: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
