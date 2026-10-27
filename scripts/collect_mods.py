from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.gamebanana import HEADERS, MAX_PER_PAGE, TIMEOUT, collect_game  # noqa: E402


def load_games() -> list[dict[str, object]]:
    return json.loads((ROOT / "config" / "games.json").read_text(encoding="utf-8"))["games"]


def output_path(game_id: int) -> Path:
    directory = ROOT / "data" / "samples"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"gamebanana_{game_id}.json"
    if path.exists():
        from datetime import datetime
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = directory / f"gamebanana_{game_id}_{suffix}.json"
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a small bounded sample of public GameBanana Mod metadata.")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--game", type=int, help="Game ID from config/games.json")
    selector.add_argument("--all-games", action="store_true", help="Explicitly collect one bounded sample for each configured game")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=10)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if args.days < 0 or args.max_pages < 1 or not 1 <= args.per_page <= MAX_PER_PAGE or args.delay < 0:
        parser.error(f"days must be >= 0, max-pages >= 1, per-page 1..{MAX_PER_PAGE}, and delay >= 0")

    games = load_games()
    selected = games if args.all_games else [game for game in games if game["game_id"] == args.game]
    if not selected:
        parser.error("unknown game ID; choose one listed in config/games.json")
    request_cap = len(selected) * args.max_pages * (1 + 1)  # one bounded retry per page
    print(f"请求上限：最多 {request_cap} 次（页面上限 {args.max_pages} × 游戏数 {len(selected)}，含每页至多一次重试）")
    exit_code = 0
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        for game in selected:
            try:
                result = collect_game(client, game, args.days, args.max_pages, args.per_page, args.delay)
            except Exception as exc:
                result = {"game": game, "days": args.days, "requested_max_pages": args.max_pages,
                          "pages_requested": 0, "actual_record_count": 0, "deduplicated_count": 0,
                          "complete_for_time_window": False, "status": "failed",
                          "failure_reasons": [{"reason": f"{type(exc).__name__}: {exc}"}], "records": []}
            path = output_path(int(game["game_id"]))
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{game['name']} ({game['game_id']}): {result['actual_record_count']} 条，去重后 {result['deduplicated_count']} 条；状态 {result['status']}；文件 {path}")
            if result["failure_reasons"] or result["status"] == "failed":
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
