"""Bounded audit of GameBanana's observable 30-day pagination boundary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.gamebanana import API_URL, HEADERS, TIMEOUT, _retry_after_seconds  # noqa: E402

GAMES = (("Genshin Impact", 8552), ("Wuthering Waves", 20357))
SORTS = (("Generic_Newest", "_tsDateAdded"), ("Generic_LatestUpdated", "_tsDateUpdated"))
MAX_PAGES = 3
PER_PAGE = 10
REPORT_PATH = ROOT / "logs" / "coverage_audit.json"


def as_utc_timestamp(value: Any) -> str | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def extract_page(payload: Any, game_id: int, page: int, sort: str) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [], {}, [f"Expected JSON object, got {type(payload).__name__}."]
    rows = payload.get("_aRecords")
    metadata = payload.get("_aMetadata")
    meta = {"fields": list(metadata) if isinstance(metadata, dict) else [],
            "_bIsComplete": metadata.get("_bIsComplete") if isinstance(metadata, dict) else None,
            "_nRecordCount": metadata.get("_nRecordCount") if isinstance(metadata, dict) else None,
            "_nPerpage": metadata.get("_nPerpage") if isinstance(metadata, dict) else None}
    if not isinstance(rows, list):
        return [], meta, ["Response is missing list _aRecords."]
    result = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append("Non-object record skipped.")
            continue
        game = row.get("_aGame")
        observed_game = game.get("_idRow") if isinstance(game, dict) else None
        if observed_game != game_id:
            errors.append(f"Item {row.get('_idRow')}: game ID mismatch ({observed_game!r}).")
            continue
        item_id = row.get("_idRow")
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            errors.append("Record has missing or invalid _idRow.")
            continue
        record = {"item_id": item_id, "game_id": game_id, "sort": sort, "page": page}
        for field in ("_tsDateAdded", "_tsDateModified", "_tsDateUpdated"):
            timestamp = row.get(field)
            if not isinstance(timestamp, int) or isinstance(timestamp, bool):
                timestamp = None
            record[field] = timestamp
            record[field + "_utc"] = as_utc_timestamp(timestamp)
        result.append(record)
    return result, meta, errors


def page_time_range(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [record.get(field) for record in records if isinstance(record.get(field), int)]
    return {
        "field": field,
        "available_count": len(values),
        "missing_count": len(records) - len(values),
        "minimum": min(values) if values else None,
        "minimum_utc": as_utc_timestamp(min(values)) if values else None,
        "maximum": max(values) if values else None,
        "maximum_utc": as_utc_timestamp(max(values)) if values else None,
    }


def duplicate_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_page: dict[int, set[int]] = {}
    totals: dict[int, int] = {}
    for record in records:
        item_id, page = record.get("item_id"), record.get("page")
        if isinstance(item_id, int) and isinstance(page, int):
            by_page.setdefault(page, set()).add(item_id)
            totals[item_id] = totals.get(item_id, 0) + 1
    repeated = {str(item_id): count for item_id, count in totals.items() if count > 1}
    overlaps = {}
    pages = sorted(by_page)
    for index, page in enumerate(pages):
        for other in pages[index + 1:]:
            common = sorted(by_page[page] & by_page[other])
            if common:
                overlaps[f"{page}:{other}"] = common
    return {"unique_count": len(totals), "repeated_ids": repeated,
            "cross_page_overlaps": overlaps,
            "cross_page_duplicate_count": sum(len(ids) for ids in overlaps.values())}


def analyze_channel(records: list[dict[str, Any]], pages: list[dict[str, Any]],
                    sort: str, time_field: str, cutoff: int,
                    errors: list[dict[str, Any]], max_pages: int = MAX_PAGES) -> dict[str, Any]:
    values = [record.get(time_field) for record in records]
    known = [value for value in values if isinstance(value, int) and not isinstance(value, bool)]
    missing_ids = [record.get("item_id") for record in records if not isinstance(record.get(time_field), int)]
    inversions = []
    comparable_pairs = 0
    for previous, current in zip(records, records[1:]):
        left, right = previous.get(time_field), current.get(time_field)
        if isinstance(left, int) and not isinstance(left, bool) and isinstance(right, int) and not isinstance(right, bool):
            comparable_pairs += 1
            if right > left:
                inversions.append({"previous_id": previous["item_id"], "previous_time": as_utc_timestamp(left),
                                   "current_id": current["item_id"], "current_time": as_utc_timestamp(right)})
    descending = not inversions and comparable_pairs > 0 and not missing_ids
    boundary_old = any(value < cutoff for value in known)
    boundary_recent = any(value >= cutoff for value in known)
    crossed = boundary_old and boundary_recent
    missing_pages = any(page.get("http_status") is None or page.get("error") for page in pages)
    capped = len(pages) >= max_pages
    old_created_recent_updated = [record.get("item_id") for record in records
                                  if isinstance(record.get("_tsDateAdded"), int)
                                  and record["_tsDateAdded"] < cutoff
                                  and isinstance(record.get("_tsDateUpdated"), int)
                                  and record["_tsDateUpdated"] >= cutoff]
    if errors or missing_pages or capped or inversions or missing_ids:
        coverage = "incomplete"
    elif crossed and descending:
        # This is only observed sample evidence; the remote sort contract is not guaranteed.
        coverage = "boundary_observed_but_unproven"
    else:
        coverage = "inconclusive"
    return {
        "sort": sort,
        "time_field": time_field,
        "record_count": len(records),
        "page_summaries": pages,
        "time_order_descending_in_sample": descending if comparable_pairs else None,
        "time_order_status": "sample_descending" if descending else "sample_inversion" if inversions else "inconclusive",
        "ordering_inversions": inversions,
        "missing_key_time_ids": missing_ids,
        "boundary_timestamp": cutoff,
        "boundary_utc": as_utc_timestamp(cutoff),
        "crossed_30_day_boundary_in_sample": crossed,
        "boundary_evidence": "both_sides_observed" if crossed else "only_older_observed" if boundary_old else "only_recent_observed" if boundary_recent else "no_usable_times",
        "old_created_recently_updated_item_ids": old_created_recent_updated,
        "coverage_status": coverage,
        "page_limit_reached": len(pages) >= max_pages,
        "errors": errors,
        "pagination": duplicate_summary(records),
    }


def request_page(client: httpx.Client, game_id: int, sort: str, page: int,
                 per_page: int = PER_PAGE) -> tuple[Any | None, dict[str, Any]]:
    params = {"_nPage": page, "_nPerpage": per_page,
              "_aFilters[Generic_Game]": game_id, "_sSort": sort}
    attempts = 0
    while True:
        try:
            response = client.get(API_URL, params=params)
            info = {"page": page, "http_status": response.status_code,
                    "request_attempts": attempts + 1, "url": str(response.request.url)}
            if response.status_code == 429:
                wait = _retry_after_seconds(response.headers.get("Retry-After"))
                info["error"] = "HTTP 429; stopped because Retry-After was missing or invalid." if wait is None else f"HTTP 429; waited {wait:g}s, then stopped all remaining scans."
                if wait is not None:
                    time.sleep(wait)
                info["stop_all"] = True
                return None, info
            response.raise_for_status()
            try:
                return response.json(), info
            except (ValueError, json.JSONDecodeError) as exc:
                info["error"] = f"Invalid JSON: {exc}"
                return None, info
        except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            if attempts == 0 and (status is None or status >= 500):
                attempts += 1
                time.sleep(1.0)
                continue
            return None, {"page": page, "http_status": status, "request_attempts": attempts + 1,
                          "error": f"{type(exc).__name__}: {exc}"}


def run_audit(client: httpx.Client, games=GAMES, max_pages: int = MAX_PAGES,
              per_page: int = PER_PAGE, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cutoff = int((now - timedelta(days=30)).timestamp())
    report: dict[str, Any] = {
        "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "target_window_days": 30,
        "boundary_utc": as_utc_timestamp(cutoff),
        "request_limits": {"games": [game_id for _, game_id in games],
                           "sorts": [sort for sort, _ in SORTS],
                           "max_pages_per_channel": max_pages, "per_page": per_page,
                           "normal_request_max": len(games) * len(SORTS) * max_pages,
                           "retry_max_per_page": 1},
        "games": {}, "actual_request_count": 0,
        "official_core_list_new_assessment": {
            "max_age_2592000_seconds": "Documented parameter for a maximum age of submissions; appropriate to test as an auxiliary 30-day new-submission query.",
            "include_updated_1": "Official docs say 1 includes new and updated submissions; useful as an auxiliary candidate query, but behavior for older existing items and completeness is not established by retained probe logs.",
            "coverage_conclusion": "Neither parameter alone proves complete coverage across both creation and source-update timelines; compare/deduplicate against apiv11 results and preserve explicit completeness state.",
            "document_url": "https://api.gamebanana.com/docs/endpoints/Core/List/New",
            "basis": "Official endpoint docs checked during this audit; prior logs retain successful Core/List/New summaries but not complete response evidence for all parameter combinations.",
        },
    }
    stop_all = False
    for game_name, game_id in games:
        game_report = {"game_name": game_name, "game_id": game_id, "channels": {}}
        for sort, time_field in SORTS:
            if stop_all:
                game_report["channels"][sort] = {"status": "not_run", "coverage_status": "inconclusive",
                                                 "errors": ["Not run after HTTP 429."], "pages": [], "records": []}
                continue
            all_records: list[dict[str, Any]] = []
            page_summaries: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []
            for page_num in range(1, max_pages + 1):
                payload, request_info = request_page(client, game_id, sort, page_num, per_page)
                report["actual_request_count"] += request_info.get("request_attempts", 1)
                if request_info.get("error"):
                    errors.append({"page": page_num, "reason": request_info["error"],
                                   "http_status": request_info.get("http_status")})
                    page_summaries.append({"page": page_num, "record_count": 0,
                                           "http_status": request_info.get("http_status"),
                                           "error": request_info["error"]})
                else:
                    rows, metadata, parse_errors = extract_page(payload, game_id, page_num, sort)
                    all_records.extend(rows)
                    row_times = [row.get(time_field) for row in rows if isinstance(row.get(time_field), int)]
                    row_inversions = sum(right > left for left, right in zip(row_times, row_times[1:]))
                    page_summaries.append({
                        "page": page_num, "record_count": len(rows),
                        "raw_record_count": len(payload.get("_aRecords", [])) if isinstance(payload, dict) and isinstance(payload.get("_aRecords"), list) else None,
                        "http_status": request_info["http_status"],
                        "time_range": page_time_range(rows, time_field),
                        "time_order_descending_in_page": (row_inversions == 0 and len(row_times) >= 2
                                                           and len(row_times) == len(rows)),
                        "time_order_inversions_in_page": row_inversions,
                        "metadata": metadata, "errors": parse_errors,
                    })
                    if parse_errors:
                        errors.extend({"page": page_num, "reason": error} for error in parse_errors)
                if request_info.get("stop_all"):
                    stop_all = True
                    break
                if page_num < max_pages:
                    time.sleep(1.0)
            analysis = analyze_channel(all_records, page_summaries, sort, time_field, cutoff, errors, max_pages)
            analysis["status"] = "failed" if not all_records and errors else "partial" if errors else "success"
            analysis["records"] = all_records
            game_report["channels"][sort] = analysis
        report["games"][str(game_id)] = game_report

    boundary_games = []
    for game_key, game_report in report["games"].items():
        crossed_sorts = [sort for sort, channel in game_report["channels"].items()
                         if channel.get("crossed_30_day_boundary_in_sample")]
        if crossed_sorts:
            boundary_games.append({"game_id": int(game_key), "game_name": game_report["game_name"],
                                   "sorts": crossed_sorts})
    report["conclusions"] = {
        "new_scan_has_trusted_boundary": False,
        "updated_scan_has_trusted_boundary": False,
        "games_observing_boundary_crossing": boundary_games,
        "coverage_status": "incomplete_or_inconclusive",
        "blocking_factors": [
            "Only three pages per channel are requested and the page cap is reached.",
            "Observed timestamp order does not establish a stable API sort contract.",
            "Missing _tsDateUpdated values can prevent a reliable updated-scan boundary check.",
            "The API does not expose a verified cursor/termination rule for the complete 30-day interval.",
        ],
        "needs_cursor_resume_or_backfill": True,
        "minimum_recommendation": "Keep per-game/per-sort checkpoints and page progress, deduplicate by (source,item_type,item_id), continue bounded backfill until a verified boundary is crossed, and reconcile with Core/List/New max_age=2592000 plus include_updated=1 as an auxiliary source.",
    }
    return report


def print_summary(report: dict[str, Any]) -> None:
    print("GameBanana 最近 30 天覆盖审计")
    print(f"UTC 边界：{report['boundary_utc']}；实际请求：{report['actual_request_count']}")
    for game_id, game in report["games"].items():
        print(f"\n{game['game_name']} ({game_id})")
        for sort, channel in game["channels"].items():
            duplicates = channel.get("pagination", {}).get("cross_page_duplicate_count", 0)
            missing = len(channel.get("missing_key_time_ids", []))
            print(f"- {sort}: {channel.get('status')}，记录 {channel.get('record_count', 0)}，跨页重复 {duplicates}，缺关键时间 {missing}，边界 {channel.get('boundary_evidence', '未观察')}，覆盖 {channel.get('coverage_status', 'inconclusive')}")
            if channel.get("ordering_inversions"):
                print(f"  排序反转 {len(channel['ordering_inversions'])} 处；样本不足以保证排序契约。")
            if channel.get("errors"):
                print(f"  错误：{channel['errors']}")
    print("\n可信完整覆盖：新增扫描否；更新扫描否。")
    print(f"30 天边界样本跨越：{report['conclusions']['games_observing_boundary_crossing']}")
    print(f"建议：{report['conclusions']['minimum_recommendation']}")


def main() -> int:
    REPORT_PATH.parent.mkdir(exist_ok=True)
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        report = run_audit(client)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(report)
    print(f"报告：{REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
