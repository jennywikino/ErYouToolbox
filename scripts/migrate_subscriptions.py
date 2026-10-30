"""Explicit, backed-up migration; never invoked by API startup."""
import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from eryoutoolbox.subscriptions import migrate

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not args.apply:
        print('No changes. Use --apply to migrate after a verified backup.')
    else:
        try:
            migrate(ROOT/'data'/'eryoutoolbox.db')
            print('Subscriptions migration complete.')
        except Exception as exc:
            parser.exit(1,f'Migration failed: {exc}\n')
