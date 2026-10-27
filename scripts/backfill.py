"""Bounded, single-game GameBanana history backfill."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.database import backup_database, connect_database  # noqa: E402
from eryoutoolbox.gamebanana import API_URL, HEADERS, MAX_PER_PAGE, TIMEOUT, _retry_after_seconds, inspect_pagination  # noqa: E402
from eryoutoolbox.importer import import_samples  # noqa: E402
from eryoutoolbox.models import normalize_record  # noqa: E402

CHANNELS = (("Generic_Newest", "_tsDateAdded"), ("Generic_LatestUpdated", "_tsDateUpdated"))


def _utc(value: int | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _request_page(client: Any, game_id: int, sort: str, page: int, per_page: int,
                  delay: float) -> tuple[Any, dict[str, Any], bool]:
    params = {"_nPage": page, "_nPerpage": per_page,
              "_aFilters[Generic_Game]": game_id, "_sSort": sort}
    attempts = 0
    while True:
        try:
            response = client.get(API_URL, params=params)
            info = {"page": page, "http_status": response.status_code, "attempts": attempts + 1}
            if response.status_code == 429:
                wait = _retry_after_seconds(response.headers.get("Retry-After"))
                if wait is not None:
                    time.sleep(wait)
                info["error"] = "HTTP 429; Retry-After honored when valid; remaining requests stopped."
                return None, info, True
            response.raise_for_status()
            try:
                return response.json(), info, False
            except (ValueError, json.JSONDecodeError) as exc:
                info["error"] = f"Invalid JSON: {exc}"
                return None, info, False
        except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            if attempts == 0 and (status is None or status >= 500):
                attempts += 1
                time.sleep(delay)
                continue
            return None, {"page": page, "http_status": status, "attempts": attempts + 1,
                          "error": f"{type(exc).__name__}: {exc}"}, False


def analyze_channel(client: Any, game: dict[str, Any], sort: str, time_field: str,
                    days: int, max_pages: int, per_page: int, delay: float,
                    cutoff: int) -> dict[str, Any]:
    raw_records: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    fetched_total = 0
    in_window_total = 0
    out_of_window_total = 0
    unknown_timestamp_total = 0
    valid_record_total = 0
    pages: list[dict[str, Any]] = []
    errors: list[str] = []
    requests = 0
    stopped_by_429 = False
    previous_times: list[int] = []
    boundary_recent_seen = False
    boundary_old_seen = False
    boundary_seen = False
    empty_page = False
    for page_number in range(1, max_pages + 1):
        payload, request, stop_all = _request_page(client, game["game_id"], sort,
                                                  page_number, per_page, delay)
        requests += request["attempts"]
        if request.get("error"):
            errors.append(f"Page {page_number}: {request['error']}")
            pages.append({**request, "record_count": 0, "time_min_utc": None, "time_max_utc": None})
            stopped_by_429 = stop_all
            break
        rows = payload.get("_aRecords") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            reason = f"Page {page_number}: expected JSON object with list _aRecords; got {type(payload).__name__}."
            errors.append(reason)
            pages.append({**request, "record_count": 0, "error": reason,
                          "time_min_utc": None, "time_max_utc": None})
            break
        fetched_total += len(rows)
        pagination = inspect_pagination(per_page, page_number, len(rows), payload.get("_aMetadata"))
        if pagination.get("error"):
            errors.append(f"Page {page_number}: {pagination['error']}")
        page_raw: list[dict[str, Any]] = []
        page_normalized: list[dict[str, Any]] = []
        page_times: list[int] = []
        missing_ids: list[int | None] = []
        for row in rows:
            if not isinstance(row, dict):
                errors.append(f"Page {page_number}: non-object record skipped.")
                continue
            nested_game = row.get("_aGame")
            if not isinstance(nested_game, dict) or nested_game.get("_idRow") != game["game_id"]:
                errors.append(f"Page {page_number}: game ID mismatch for item {row.get('_idRow')!r}; skipped.")
                continue
            record = normalize_record(row, game)
            if not isinstance(record.get("item_type"), str) or not isinstance(record.get("item_id"), int):
                errors.append(f"Page {page_number}: invalid item identity; skipped.")
                continue
            value = row.get(time_field)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                page_times.append(value)
                if value >= cutoff:
                    normalized.append(record)
                    in_window_total += 1
                else:
                    out_of_window_total += 1
            else:
                missing_ids.append(record["item_id"])
                unknown_timestamp_total += 1
            page_raw.append({"item_id": record["item_id"], "page": page_number,
                             "_tsDateAdded": row.get("_tsDateAdded"),
                             "_tsDateModified": row.get("_tsDateModified"),
                             "_tsDateUpdated": row.get("_tsDateUpdated")})
            page_normalized.append(record)
            valid_record_total += 1
        inversions = sum(right > left for left, right in zip(page_times, page_times[1:]))
        inversions += sum(right > left for left, right in zip(previous_times[-1:], page_times[:1])) if previous_times and page_times else 0
        previous_times.extend(page_times)
        page_summary = {
            **request, "record_count": len(page_normalized),
            "time_min_utc": _utc(min(page_times)) if page_times else None,
            "time_max_utc": _utc(max(page_times)) if page_times else None,
            "missing_timestamp_ids": missing_ids,
            "time_order_descending": bool(page_times) and inversions == 0 and not missing_ids,
            "ordering_inversions": inversions,
            "metadata_fields": sorted(payload.get("_aMetadata", {}).keys())
                               if isinstance(payload.get("_aMetadata"), dict) else [],
            "pagination": pagination,
        }
        pages.append(page_summary)
        raw_records.extend(page_raw)
        if not rows:
            empty_page = True
            break
        boundary_recent_seen = boundary_recent_seen or any(value >= cutoff for value in page_times)
        boundary_old_seen = boundary_old_seen or any(value < cutoff for value in page_times)
        boundary_seen = boundary_recent_seen and boundary_old_seen
        # Early termination uses only observed, complete descending timestamps and is
        # explicitly reported as an observed boundary, never as guaranteed completeness.
        if boundary_seen and not missing_ids and inversions == 0:
            break
        if pagination.get("end_of_results"):
            break
        if page_number < max_pages:
            time.sleep(delay)

    seen: set[tuple[Any, Any, Any]] = set()
    unique: list[dict[str, Any]] = []
    for item in normalized:
        key = (item.get("source"), item.get("item_type"), item.get("item_id"))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    ids_by_page: dict[int, set[int]] = {}
    for item in raw_records:
        ids_by_page.setdefault(item["page"], set()).add(item["item_id"])
    overlap_ids: set[int] = set()
    page_nums = sorted(ids_by_page)
    for index, page_num in enumerate(page_nums):
        for later_page in page_nums[index + 1:]:
            overlap_ids.update(ids_by_page[page_num] & ids_by_page[later_page])
    all_times = [r[time_field] for r in raw_records if isinstance(r.get(time_field), int)
                 and not isinstance(r.get(time_field), bool) and r[time_field] > 0]
    all_missing = [r["item_id"] for r in raw_records if not isinstance(r.get(time_field), int)
                   or isinstance(r.get(time_field), bool) or r[time_field] <= 0]
    all_inversions = sum(right > left for left, right in zip(previous_times, previous_times[1:]))
    if errors:
        coverage_status = "inconclusive"
        status = "partial" if valid_record_total else "failed"
    elif all_missing or all_inversions:
        coverage_status = "inconclusive"
        status = "partial" if valid_record_total else "failed"
    elif overlap_ids:
        coverage_status = "inconclusive"
        status = "partial"
    elif boundary_recent_seen and boundary_old_seen:
        coverage_status = "boundary_observed"
        status = "success"
    else:
        coverage_status = "incomplete"
        status = "partial" if valid_record_total else "failed"
    return {
        "sort": sort, "time_field": time_field, "status": status,
        "pages_requested": len(pages), "requests": requests,
        "records_fetched": fetched_total, "valid_records": valid_record_total,
        "in_window_count": in_window_total, "out_of_window_count": out_of_window_total,
        "unknown_timestamp_count": unknown_timestamp_total, "unique_records": len(unique),
        "oldest_timestamp": _utc(min(all_times)) if all_times else None,
        "newest_timestamp": _utc(max(all_times)) if all_times else None,
        "missing_timestamp_ids": all_missing, "duplicate_ids": sorted(overlap_ids),
        "boundary_status": "observed" if boundary_recent_seen and boundary_old_seen else "not_observed",
        "coverage_status": coverage_status, "page_limit_reached": len(pages) >= max_pages,
        "empty_page": empty_page, "ordering_inversions": all_inversions,
        "time_order_descending": bool(all_times) and all_inversions == 0 and not all_missing,
        "pages": pages, "errors": errors, "records": unique,
        "rate_limited": stopped_by_429,
    }


def run_backfill(game: dict[str, Any], client: Any, connection: Any, days: int = 30,
                 max_pages: int = 5, per_page: int = 10, dry_run: bool = True,
                 before_write: Callable[[], None] | None = None,
                 now: datetime | None = None, delay: float = 1.0) -> dict[str, Any]:
    if days < 1 or max_pages < 1 or max_pages > 20 or not 1 <= per_page <= MAX_PER_PAGE:
        raise ValueError(f"days must be positive, max_pages 1..20, per_page 1..{MAX_PER_PAGE}")
    now = now or datetime.now(timezone.utc)
    cutoff = int((now.astimezone(timezone.utc) - timedelta(days=days)).timestamp())
    channels: dict[str, Any] = {}
    all_records: list[dict[str, Any]] = []
    rate_limited = False
    for sort, field in CHANNELS:
        if rate_limited:
            channels[sort] = {"sort": sort, "time_field": field, "status": "not_run",
                              "coverage_status": "inconclusive", "records": [], "requests": 0,
                              "pages_requested": 0, "errors": ["Not run after HTTP 429."]}
            continue
        result = analyze_channel(client, game, sort, field, days, max_pages, per_page,
                                 delay, cutoff)
        channels[sort] = result
        all_records.extend(result.get("records", []))
        rate_limited = result.get("rate_limited", False)
    unique_map: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for record in all_records:
        key = (record.get("source"), record.get("item_type"), record.get("item_id"))
        previous = unique_map.get(key)
        if previous is None:
            unique_map[key] = dict(record)
        else:
            # Prefer a record with explicit newer source update time; fill absent metadata.
            old_update, new_update = previous.get("updated_at_timestamp"), record.get("updated_at_timestamp")
            preferred, fallback = (record, previous) if (new_update or 0) >= (old_update or 0) else (previous, record)
            merged = dict(fallback)
            merged.update({key_name: value for key_name, value in preferred.items()
                           if value not in (None, "", [])})
            unique_map[key] = merged
    records = list(unique_map.values())
    started = now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    snapshot = ({"path": f"backfill:{game['game_id']}", "captured_at": now.astimezone(timezone.utc),
                 "captured_at_raw": started}, records)
    errors = [{"sort": sort, "reason": reason} for sort, channel in channels.items()
              for reason in channel.get("errors", [])]
    statuses = [c.get("status") for c in channels.values()]
    if not records:
        overall = "failed"
    elif any(status in {"partial", "failed", "not_run"} for status in statuses):
        overall = "partial"
    else:
        overall = "success"
    result: dict[str, Any] = {
        "game": game, "days": days, "boundary_utc": _utc(cutoff), "channels": channels,
        "fetched_total": sum(c.get("records_fetched", 0) for c in channels.values()),
        "in_window_total": sum(c.get("in_window_count", 0) for c in channels.values()),
        "out_of_window_total": sum(c.get("out_of_window_count", 0) for c in channels.values()),
        "unknown_timestamp_total": sum(c.get("unknown_timestamp_count", 0) for c in channels.values()),
        "unique_total": len(records), "requests_total": sum(c.get("requests", 0) for c in channels.values()),
        "coverage": overall_coverage(channels),
        "overall_status": overall, "errors": errors, "backup_path": None,
    }
    imported: dict[str, Any] = {}
    try:
        imported = import_samples(connection, [snapshot], dry_run=dry_run,
                                  now=started, before_write=before_write)
    except Exception as exc:
        result["overall_status"] = "failed"
        result["database_error"] = f"{type(exc).__name__}: {exc}"
        imported = {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0,
                    "new_events": 0, "metadata_events": 0, "source_update_events": 0}
    result.update(imported)
    result["events"] = sum(imported.get(name, 0) for name in
                           ("new_events", "metadata_events", "source_update_events"))
    result["database_total"] = connection.execute("SELECT COUNT(*) FROM mods").fetchone()[0]
    result["coverage"] = overall_coverage(channels)
    return result


def overall_coverage(channels: dict[str, dict[str, Any]]) -> str:
    """A global boundary requires both scans and no channel-level uncertainty."""
    if any(channel.get("coverage_status") == "incomplete"
           for channel in channels.values()):
        return "incomplete"
    if any(channel.get("coverage_status") == "inconclusive"
           for channel in channels.values()):
        return "inconclusive"
    if any(channel.get("coverage_status") != "boundary_observed"
           or channel.get("status") != "success" for channel in channels.values()):
        return "incomplete"
    if len(channels) != len(CHANNELS):
        return "incomplete"
    return "boundary_observed"


def load_games() -> list[dict[str, Any]]:
    return json.loads((ROOT / "config" / "games.json").read_text(encoding="utf-8"))["games"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded, single-game history backfill.")
    parser.add_argument("--game", type=int, required=True, help="Game ID from config/games.json")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--per-page", type=int, default=10)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    mode.add_argument("--apply", action="store_true", help="Back up and write changes")
    return parser


def print_summary(result: dict[str, Any], dry_run: bool) -> None:
    print("GameBanana bounded backfill")
    print(f"Game: {result['game']['name']}\nGame ID: {result['game']['game_id']}\nTarget boundary UTC: {result['boundary_utc']}")
    for sort, channel in result["channels"].items():
        print(f"\n{sort}")
        print(f"Pages requested: {channel.get('pages_requested', 0)} | Fetched total: {channel.get('records_fetched', 0)} | In-window: {channel.get('in_window_count', 0)} | Out-of-window: {channel.get('out_of_window_count', 0)} | Unique in-window: {channel.get('unique_records', 0)}")
        print(f"Oldest timestamp: {channel.get('oldest_timestamp')} | Newest timestamp: {channel.get('newest_timestamp')}")
        print(f"Missing timestamps: {len(channel.get('missing_timestamp_ids', []))} | Duplicate IDs: {len(channel.get('duplicate_ids', []))} | Boundary: {channel.get('boundary_status')} | Coverage: {channel.get('coverage_status')}")
        print(f"Failure reason: {'; '.join(channel.get('errors', [])) or 'none'}")
        for page in channel.get("pages", []):
            print(f"  Page {page['page']}: {page['record_count']} records, {page.get('time_min_utc')} .. {page.get('time_max_utc')}, descending={page.get('time_order_descending')}")
    print("\nGlobal")
    print(f"Fetched total: {result['fetched_total']} | In-window total: {result['in_window_total']} | Unique total: {result['unique_total']} | Out-of-window total: {result['out_of_window_total']} | Inserted: {result.get('inserted', 0)} | Updated: {result.get('updated', 0)} | Unchanged: {result.get('unchanged', 0)} | Events: {result.get('events', 0)}")
    print(f"Requests total: {result['requests_total']} | Database total: {result['database_total']} | Coverage: {result['coverage']} | Overall status: {result['overall_status']} ({'dry-run' if dry_run else 'apply'})")
    if result.get("database_error"):
        print(f"Database failure: {result['database_error']}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.days < 1 or args.max_pages < 1 or args.max_pages > 20 or not 1 <= args.per_page <= MAX_PER_PAGE:
        parser.error(f"days must be positive, max-pages 1..20, per-page 1..{MAX_PER_PAGE}")
    game = next((item for item in load_games() if item.get("game_id") == args.game), None)
    if game is None:
        parser.error("Unknown game ID; choose one from config/games.json")
    db_path = ROOT / "data" / "eryoutoolbox.db"
    if not db_path.is_file():
        parser.error("Database is missing; run scripts/init_db.py first")
    connection = connect_database(db_path)
    backup_path: Path | None = None

    def create_backup() -> None:
        nonlocal backup_path
        backup_dir = ROOT / "data" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"eryoutoolbox_backfill_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.db"
        if backup_path.exists():
            raise FileExistsError(f"Refusing to overwrite backup {backup_path}")
        backup_database(db_path, backup_path)

    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
            result = run_backfill(game, client, connection, args.days, args.max_pages,
                                  args.per_page, dry_run=not args.apply,
                                  before_write=create_backup if args.apply else None)
        result["backup_path"] = str(backup_path) if backup_path else None
        print_summary(result, dry_run=not args.apply)
        return 1 if result.get("database_error") or result["overall_status"] == "failed" else 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
