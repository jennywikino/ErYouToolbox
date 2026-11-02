"""Bounded preview by default; apply only an explicitly selected reviewed report."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from eryoutoolbox.author_updates import preview,apply_report
from backfill_content_ratings import instance_lock

def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true')
    mode.add_argument('--apply-report',type=Path)
    p.add_argument('--resume-report',type=Path)
    p.add_argument('--pages',type=int,default=1)
    p.add_argument('--details',type=int,default=5)
    a=p.parse_args()
    try:
        if a.apply_report:
            with instance_lock(ROOT/'logs/content_ratings/instance.lock'):
                print(json.dumps(apply_report(ROOT/'data/eryoutoolbox.db',json.loads(a.apply_report.read_text(encoding='utf-8')))))
        else:
            report,path=preview(ROOT/'data/eryoutoolbox.db',ROOT,
                json.loads(a.resume_report.read_text(encoding='utf-8')) if a.resume_report else None,a.pages,a.details)
            print(json.dumps(report,ensure_ascii=True,indent=2));print('Report:',path)
    except Exception as exc:p.exit(1,f'Check failed: {type(exc).__name__}: {exc}\n')
if __name__=='__main__':main()
