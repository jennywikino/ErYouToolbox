"""Import at most 20 explicitly verified source rating samples. Default: dry-run."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from eryoutoolbox.content_ratings import save_verified_samples
from eryoutoolbox.database import backup_database
from eryoutoolbox.ui_queries import readonly_connection
import sqlite3

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    database = ROOT / 'data' / 'eryoutoolbox.db'
    backup = None
    def before_write():
        nonlocal backup
        backup = ROOT / 'data' / 'backups' / ('ratings_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.db')
        if backup.exists():
            raise FileExistsError(backup)
        backup_database(database, backup)
    connection = None
    try:
        report = json.loads(args.report.read_text(encoding='utf-8'))
        if not database.is_file():
            raise FileNotFoundError(database)
        connection = (sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=5)
                      if args.apply else readonly_connection(database))
        result = save_verified_samples(connection, report, dry_run=not args.apply, before_write=before_write)
        print(json.dumps({**result, 'dry_run': not args.apply, 'backup': str(backup) if backup else None}))
        return 0
    except Exception as exc:
        print(f'Failed: {type(exc).__name__}: {exc}')
        return 1
    finally:
        if connection is not None:
            connection.close()

if __name__ == '__main__':
    raise SystemExit(main())
