"""Explicit read-state migration; no automatic production migration."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from eryoutoolbox.subscriptions import migrate
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if not args.apply:print('No changes. Use --apply for verified-backup migration to schema 3.')
    else:
        try:migrate(ROOT/'data/eryoutoolbox.db');print('Read-state migration complete.')
        except Exception as exc:parser.exit(1,f'Migration failed: {exc}\n')
