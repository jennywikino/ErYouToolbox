from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.database import backup_database, connect_database  # noqa: E402
from eryoutoolbox.gamebanana import HEADERS, MAX_PER_PAGE, TIMEOUT, collect_game  # noqa: E402
from eryoutoolbox.importer import import_samples  # noqa: E402

SORTS = (("new_scan", "Generic_Newest"), ("updated_scan", "Generic_LatestUpdated"))


def _key(record: dict[str, Any]) -> tuple[Any, Any, Any]:
    return record.get("source"), record.get("item_type"), record.get("item_id")


def _missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def merge_scan_records(scans: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Merge both scans by identity, preferring later explicit updated_at evidence."""
    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    fetched = 0
    for scan in scans:
        for incoming in scan.get("records", []):
            if not isinstance(incoming, dict) or not incoming.get("source") or not incoming.get("item_type") or not incoming.get("item_id"):
                continue
            fetched += 1
            key = _key(incoming)
            current = merged.get(key)
            if current is None:
                merged[key] = dict(incoming)
                continue
            old_update = _parse_time(current.get("updated_at"))
            new_update = _parse_time(incoming.get("updated_at"))
            if old_update is not None and new_update is not None and old_update > new_update:
                preferred, fallback = current, incoming
            else:
                # Equal or absent source timestamps: second scan is the later observation.
                preferred, fallback = incoming, current
            combined = dict(fallback)
            combined.update({key_name: value for key_name, value in preferred.items() if not _missing(value)})
            for key_name, value in fallback.items():
                if key_name not in combined or _missing(combined[key_name]):
                    combined[key_name] = value
            merged[key] = combined
    return list(merged.values()), fetched


def run_sync(game: dict[str, Any], client: Any, connection: Any, max_pages: int = 1,
             per_page: int = 10, dry_run: bool = True, before_write=None,
             started_at: str | None = None, ended_at: str | None = None,
             identity_registry: dict[tuple[Any, Any, Any], int] | None = None) -> dict[str, Any]:
    if max_pages < 1 or max_pages > 20:
        raise ValueError("max_pages must be between 1 and 20")
    if per_page < 1 or per_page > MAX_PER_PAGE:
        raise ValueError(f"per_page must be between 1 and {MAX_PER_PAGE}")
    started = started_at or datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    scans: dict[str, Any] = {}
    scan_results: list[dict[str, Any]] = []
    request_count = 0
    stop_after_rate_limit = False

    for scan_name, sort in SORTS:
        if stop_after_rate_limit:
            scans[scan_name] = {"sort": sort, "status": "not_run", "request_count": 0,
                                "records": [], "errors": ["Stopped after HTTP 429 in the previous scan."]}
            continue
        try:
            result = collect_game(client, game, max_pages=max_pages, per_page=per_page,
                                  delay=0.0, sort=sort)
            errors = [str(item.get("reason", item)) for item in result.get("failure_reasons", [])]
            requests = int(result.get("request_count", result.get("pages_requested", 0)))
            request_count += requests
            successful = result.get("pages_requested", 0) > 0 and not errors
            status = "success" if successful else "partial" if result.get("records") else "failed"
            scans[scan_name] = {"sort": sort, "status": status, "request_count": requests,
                                "fetched": result.get("actual_record_count", len(result.get("records", []))),
                                "records": result.get("records", []), "errors": errors,
                                "pages_requested": result.get("pages_requested", 0)}
            scan_results.append(scans[scan_name])
            if any(item.get("http_status") == 429 for item in result.get("failure_reasons", [])):
                stop_after_rate_limit = True
        except Exception as exc:
            scans[scan_name] = {"sort": sort, "status": "failed", "request_count": 0,
                                "fetched": 0, "records": [],
                                "errors": [f"{type(exc).__name__}: {exc}"]}
            scan_results.append(scans[scan_name])

    records, fetched = merge_scan_records(scan_results)
    usable_scans = sum(scan["status"] in {"success", "partial"} for scan in scans.values())
    any_scan_issue = any(scan["status"] != "success" for scan in scans.values())
    if usable_scans == 0:
        sync_status = "failed"
    elif any_scan_issue:
        sync_status = "partial"
    else:
        sync_status = "success"
    errors = [{"scan": name, "sort": value["sort"], "reason": message}
              for name, value in scans.items() for message in value.get("errors", [])]

    # The existing database identity key is (source, item_type, item_id). If an
    # impossible cross-game ID collision is seen, do not overwrite the other game's row.
    accepted_records = []
    cross_game_conflicts = 0
    for record in records:
        key = _key(record)
        known_game_id = identity_registry.get(key) if identity_registry is not None else None
        if known_game_id is None:
            existing = connection.execute(
                "SELECT game_id FROM mods WHERE source=? AND item_type=? AND item_id=?", key
            ).fetchone()
            known_game_id = existing[0] if existing is not None else None
        if known_game_id is not None and known_game_id != game["game_id"]:
            cross_game_conflicts += 1
            errors.append({"scan": "merge", "sort": None,
                           "reason": f"Identity collision with game_id={known_game_id}; record was skipped to avoid cross-game merge.",
                           "identity": key})
            continue
        accepted_records.append(record)
        if identity_registry is not None:
            identity_registry[key] = game["game_id"]
    records = accepted_records
    if cross_game_conflicts and sync_status == "success":
        sync_status = "partial"

    ended = ended_at or datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    snapshot = ({"path": f"sync:{game['game_id']}", "captured_at": _parse_time(ended),
                 "captured_at_raw": ended}, records)
    sync_run = {
        "source": "gamebanana", "game_id": game["game_id"],
        "started_at": started, "ended_at": ended, "status": sync_status,
        "request_count": request_count, "fetched_count": fetched,
        "deduplicated_count": len(records), "errors": errors,
    }
    try:
        imported = import_samples(connection, [snapshot], dry_run=dry_run,
                                  now=ended, before_write=before_write,
                                  sync_run=None if dry_run else sync_run)
        sync_error = None
    except Exception as exc:
        imported = {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0,
                    "new_events": 0, "metadata_events": 0, "source_update_events": 0}
        sync_error = f"Database transaction failed: {type(exc).__name__}: {exc}"
        sync_status = "failed"

    return {
        "game": game, "scans": scans, "requests": request_count,
        "fetched": fetched, "unique": len(records), "coverage": "incomplete",
        "sync_status": sync_status, "errors": errors,
        "rate_limited": stop_after_rate_limit,
        "cross_game_conflicts": cross_game_conflicts,
        "database_error": sync_error,
        "backup_path": None,
        **imported,
        "skipped": imported.get("skipped", 0) + cross_game_conflicts,
    }


def load_games() -> list[dict[str, Any]]:
    return json.loads((ROOT / "config" / "games.json").read_text(encoding="utf-8"))["games"]


def run_all_games(games: list[dict[str, Any]], client: Any, connection: Any,
                  max_pages: int = 1, per_page: int = 10, dry_run: bool = True,
                  before_write=None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    identity_registry: dict[tuple[Any, Any, Any], int] = {}
    stopped = False
    for index, game in enumerate(games):
        if stopped:
            results.append({
                "game": game, "status": "skipped", "sync_status": "skipped",
                "scans": {name: {"sort": sort, "status": "not_run", "fetched": 0, "errors": []}
                          for name, sort in SORTS},
                "requests": 0, "fetched": 0, "unique": 0, "inserted": 0,
                "updated": 0, "unchanged": 0, "skipped": 0,
                "new_events": 0, "metadata_events": 0, "source_update_events": 0,
                "coverage": "incomplete", "errors": ["Not run because a previous game received HTTP 429."],
            })
            continue
        try:
            result = run_sync(game, client, connection, max_pages, per_page,
                              dry_run=dry_run, before_write=before_write,
                              identity_registry=identity_registry)
        except Exception as exc:
            result = {
                "game": game, "sync_status": "failed", "scans": {}, "requests": 0,
                "fetched": 0, "unique": 0, "inserted": 0, "updated": 0,
                "unchanged": 0, "skipped": 0, "new_events": 0,
                "metadata_events": 0, "source_update_events": 0,
                "coverage": "incomplete", "errors": [
                    {"scan": "database", "sort": None,
                     "reason": f"{type(exc).__name__}: {exc}"}],
                "database_error": str(exc), "rate_limited": False,
            }
        result["status"] = result.get("sync_status", "failed")
        results.append(result)
        if result.get("rate_limited"):
            stopped = True

    success = sum(item["status"] == "success" for item in results)
    partial = sum(item["status"] == "partial" for item in results)
    failed = sum(item["status"] == "failed" for item in results)
    skipped_games = sum(item["status"] == "skipped" for item in results)
    attempted = len(results) - skipped_games
    if failed == attempted and attempted > 0 and skipped_games == 0:
        overall = "failed"
    elif partial or failed or skipped_games:
        overall = "partial"
    else:
        overall = "success"
    return {
        "games": results,
        "games_attempted": attempted,
        "games_success": success,
        "games_partial": partial,
        "games_failed": failed,
        "games_skipped": skipped_games,
        "requests_total": sum(item.get("requests", 0) for item in results),
        "fetched_total": sum(item.get("fetched", 0) for item in results),
        "unique_total": sum(item.get("unique", 0) for item in results),
        "inserted_total": sum(item.get("inserted", 0) for item in results),
        "updated_total": sum(item.get("updated", 0) for item in results),
        "events_total": sum(item.get("new_events", 0) + item.get("metadata_events", 0)
                             + item.get("source_update_events", 0) for item in results),
        "coverage": "incomplete",
        "overall_status": overall,
    }


def _error_text(result: dict[str, Any]) -> str:
    errors = result.get("errors", [])
    if isinstance(errors, list):
        texts = [str(item.get("reason", item)) if isinstance(item, dict) else str(item) for item in errors]
        if result.get("database_error"):
            texts.append(result["database_error"])
        return "; ".join(texts) or "none"
    return str(errors)


def print_all_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("GameBanana Sync")
    for result in summary["games"]:
        game = result["game"]
        scans = result.get("scans", {})
        new_scan = scans.get("new_scan", {})
        updated_scan = scans.get("updated_scan", {})
        print(f"\nGame: {game['name']}\nGame ID: {game['game_id']}")
        print(f"New scan: {new_scan.get('status', 'not_run')}\nUpdated scan: {updated_scan.get('status', 'not_run')}")
        print(f"Fetched: {result.get('fetched', 0)}\nUnique: {result.get('unique', 0)}")
        print(f"Inserted: {result.get('inserted', 0)}\nUpdated: {result.get('updated', 0)}\nUnchanged: {result.get('unchanged', 0)}")
        print(f"Events: {result.get('new_events', 0) + result.get('metadata_events', 0) + result.get('source_update_events', 0)}")
        print(f"Coverage: {result.get('coverage', 'incomplete')}\nStatus: {result.get('status', 'failed')}")
        print(f"Error: {_error_text(result)}")
    print("\nGlobal summary")
    print(f"Games attempted: {summary['games_attempted']}\nGames success: {summary['games_success']}\nGames partial: {summary['games_partial']}\nGames failed: {summary['games_failed']}\nGames skipped: {summary['games_skipped']}")
    print(f"Requests total: {summary['requests_total']}\nFetched total: {summary['fetched_total']}\nUnique total: {summary['unique_total']}\nInserted total: {summary['inserted_total']}\nUpdated total: {summary['updated_total']}\nEvents total: {summary['events_total']}")
    print(f"Coverage: {summary['coverage']}\nOverall status: {summary['overall_status']} ({'dry-run' if dry_run else 'apply'})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded GameBanana sync.")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--game", type=int, help="One game ID from config/games.json")
    selector.add_argument("--all-games", action="store_true", help="Sequentially sync all configured games")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=10)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    mode.add_argument("--apply", action="store_true", help="Back up and write changes")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_pages < 1 or args.max_pages > 20 or args.per_page < 1 or args.per_page > MAX_PER_PAGE:
        parser.error(f"max-pages must be 1..20 and per-page must be 1..{MAX_PER_PAGE}")
    configured_games = load_games()
    games = configured_games if args.all_games else [entry for entry in configured_games if entry.get("game_id") == args.game]
    if not games:
        parser.error("Unknown game ID; choose one from config/games.json")
    database_path = ROOT / "data" / "eryoutoolbox.db"
    if not database_path.is_file():
        parser.error("Database is missing; run scripts/init_db.py first")

    connection = connect_database(database_path)
    backup_path: Path | None = None

    def create_backup() -> None:
        nonlocal backup_path
        backup_dir = ROOT / "data" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_dir / f"eryoutoolbox_{stamp}.db"
        if backup_path.exists():
            raise FileExistsError(f"Refusing to overwrite backup {backup_path}")
        backup_database(database_path, backup_path)

    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
            if args.all_games:
                budget = len(games) * 2 * args.max_pages * 2
                print(f"Maximum HTTP request budget: {budget} (includes one retry per page).")
                summary = run_all_games(games, client, connection, args.max_pages, args.per_page,
                                        dry_run=not args.apply,
                                        before_write=create_backup if args.apply else None)
                print_all_summary(summary, dry_run=not args.apply)
                return 1 if summary["games_failed"] else 0
            result = run_sync(games[0], client, connection, args.max_pages, args.per_page,
                              dry_run=not args.apply,
                              before_write=create_backup if args.apply else None)
        result["database"] = str(database_path)
        result["backup_path"] = str(backup_path) if backup_path else None
        print_summary(result, dry_run=not args.apply)
        return 1 if result.get("database_error") or result.get("sync_status") == "failed" else 0
    finally:
        connection.close()


def print_summary(result: dict[str, Any], dry_run: bool) -> None:
    game = result["game"]
    print("GameBanana Sync")
    print(f"Game: {game['name']}\nGame ID: {game['game_id']}")
    for label, key in (("New scan", "new_scan"), ("Updated scan", "updated_scan")):
        scan = result["scans"].get(key, {})
        print(f"{label}: {scan.get('status', 'not_run')} ({scan.get('sort', '')}; {scan.get('fetched', 0)} records)")
        for error in scan.get("errors", []):
            print(f"  Error: {error}")
    print(f"Requests: {result['requests']}\nFetched: {result['fetched']}\nUnique: {result['unique']}")
    print(f"Inserted: {result.get('inserted', 0)}\nUpdated: {result.get('updated', 0)}\nUnchanged: {result.get('unchanged', 0)}\nSkipped: {result.get('skipped', 0)}")
    print(f"New events: {result.get('new_events', 0)}\nUpdate events: {result.get('metadata_events', 0) + result.get('source_update_events', 0)}")
    print(f"Coverage: {result['coverage']}\nSync status: {result['sync_status']} ({'dry-run' if dry_run else 'apply'})")
    if result.get("database_error"):
        print(f"Database error: {result['database_error']}")
    print(f"Database: {result.get('database', '(temporary test database)')}\nBackup: {result.get('backup_path') or 'none'}")


if __name__ == "__main__":
    raise SystemExit(main())
