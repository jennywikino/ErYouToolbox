"""Bounded GameBanana pagination and timestamp ordering audit for Genshin Impact."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.gamebanana import API_URL, HEADERS, TIMEOUT, _retry_after_seconds  # noqa: E402

GAME_ID = 8552
SORTS = ("Generic_Newest", "Generic_NewAndUpdated", "Generic_LatestUpdated")
PER_PAGE = 10
MAX_PAGES = 2
REPORT_PATH = ROOT / "logs" / "pagination_audit.json"
TIME_FIELDS = ("_tsDateAdded", "_tsDateModified", "_tsDateUpdated")


def timestamp_utc(value: Any) -> str | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def extract_records(payload: Any, sort: str, page: int) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    failures: list[str] = []
    if not isinstance(payload, dict):
        return [], [], [f"Expected JSON object, got {type(payload).__name__}."]
    rows = payload.get("_aRecords")
    metadata = payload.get("_aMetadata")
    metadata_fields = list(metadata.keys()) if isinstance(metadata, dict) else []
    if not isinstance(rows, list):
        return [], metadata_fields, ["Response has no list _aRecords."]
    result = []
    for row in rows:
        if not isinstance(row, dict):
            failures.append("Non-object row skipped.")
            continue
        game = row.get("_aGame")
        found_game_id = game.get("_idRow") if isinstance(game, dict) else None
        if found_game_id != GAME_ID:
            failures.append(f"Item {row.get('_idRow')}: missing or mismatched game ID {found_game_id!r}.")
            continue
        item = {"item_id": row.get("_idRow"), "sort": sort, "page": page}
        for field in TIME_FIELDS:
            item[field] = row.get(field) if isinstance(row.get(field), int) and not isinstance(row.get(field), bool) else None
            item[field + "_utc"] = timestamp_utc(item[field])
        result.append(item)
    return result, metadata_fields, failures


def duplicate_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_page: dict[int, set[Any]] = {1: set(), 2: set()}
    counts = Counter()
    for record in records:
        counts[record.get("item_id")] += 1
        by_page.setdefault(record.get("page"), set()).add(record.get("item_id"))
    duplicates = {str(item_id): count for item_id, count in counts.items() if item_id is not None and count > 1}
    cross_page = sorted(by_page.get(1, set()) & by_page.get(2, set()), key=str)
    return {"unique_count": len(counts), "duplicate_ids": duplicates,
            "cross_page_duplicate_ids": cross_page, "cross_page_duplicate_count": len(cross_page)}


def ordering_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    analysis = {}
    for field in TIME_FIELDS:
        values = [record[field] for record in records if isinstance(record.get(field), int)]
        desc = all(left >= right for left, right in zip(values, values[1:]))
        asc = all(left <= right for left, right in zip(values, values[1:]))
        analysis[field] = {
            "available_count": len(values),
            "descending_monotonic": desc if len(values) >= 2 else None,
            "ascending_monotonic": asc if len(values) >= 2 else None,
            "status": "inconclusive" if len(values) < 2 or (desc and asc) else "sample_descending" if desc else "sample_ascending" if asc else "not_monotonic",
        }
    return analysis


def analyze_sort(records: list[dict[str, Any]], now_ts: int | None = None) -> dict[str, Any]:
    now_ts = int(time.time()) if now_ts is None else now_ts
    cutoff = now_ts - 30 * 86400
    ids = {record.get("item_id") for record in records if record.get("item_id") is not None}
    missing_updated = [record["item_id"] for record in records if record.get("_tsDateUpdated") is None]
    modified_only = [record["item_id"] for record in records
                     if record.get("_tsDateModified") is not None and record.get("_tsDateUpdated") is None]
    old_created_recent_updated = [record["item_id"] for record in records
                                  if record.get("_tsDateAdded") is not None
                                  and record["_tsDateAdded"] < cutoff
                                  and record.get("_tsDateUpdated") is not None
                                  and record["_tsDateUpdated"] >= cutoff]
    candidates = [record.get(field) for record in records for field in TIME_FIELDS
                  if isinstance(record.get(field), int)]
    straddles_30d = bool(candidates and min(candidates) < cutoff <= max(candidates))
    return {
        "record_count": len(records),
        "unique_item_ids": sorted(ids, key=str),
        "missing_updated_count": len(missing_updated),
        "missing_updated_item_ids": missing_updated,
        "modified_without_updated_count": len(modified_only),
        "modified_without_updated_item_ids": modified_only,
        "old_created_recent_updated_item_ids": old_created_recent_updated,
        "time_ordering": ordering_analysis(records),
        "timestamp_range_straddles_30_days": straddles_30d,
        "thirty_day_boundary_status": "sample_straddles_boundary; API window filtering remains unverified" if straddles_30d else "inconclusive",
        "metadata_note": "_aMetadata fields are reported as-is; _bIsComplete is not interpreted as 30-day coverage.",
    }


def fetch_page(client: httpx.Client, sort: str, page: int) -> tuple[Any | None, dict[str, Any]]:
    params = {"_nPage": page, "_nPerpage": PER_PAGE,
              "_aFilters[Generic_Game]": GAME_ID, "_sSort": sort}
    attempts = 0
    while True:
        try:
            response = client.get(API_URL, params=params)
            info = {"sort": sort, "page": page, "http_status": response.status_code,
                    "url": str(response.request.url), "request_attempts": attempts + 1}
            if response.status_code == 429:
                retry = _retry_after_seconds(response.headers.get("Retry-After"))
                info["failure_reason"] = "HTTP 429; stopped because Retry-After was absent or invalid." if retry is None else f"HTTP 429; waited {retry:g}s then stopped."
                if retry is not None:
                    time.sleep(retry)
                info["stop_all"] = True
                return None, info
            response.raise_for_status()
            try:
                return response.json(), info
            except (ValueError, json.JSONDecodeError) as exc:
                info["failure_reason"] = f"Invalid JSON: {exc}"
                return None, info
        except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            if attempts == 0 and (status is None or status >= 500):
                attempts += 1
                time.sleep(1.0)
                continue
            return None, {"sort": sort, "page": page, "http_status": status, "request_attempts": attempts + 1,
                          "failure_reason": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    report: dict[str, Any] = {
        "game_id": GAME_ID, "game_name": "Genshin Impact",
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_limits": {"sorts": list(SORTS), "max_pages_per_sort": MAX_PAGES,
                           "per_page": PER_PAGE, "normal_request_max": 6,
                           "retry_max_per_request": 1},
        "sorts": {}, "cross_sort_comparison": {},
        "conclusions": {"sort_semantics": "inconclusive", "thirty_day_boundary": "inconclusive"},
    }
    stop_all = False
    request_count = 0
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        for sort in SORTS:
            sort_result = {"requests": [], "records": [], "metadata_fields": [], "metadata_samples": []}
            for page in (1, 2):
                payload, request_info = fetch_page(client, sort, page)
                request_count += request_info.get("request_attempts", 1)
                sort_result["requests"].append(request_info)
                if payload is not None:
                    records, metadata_fields, failures = extract_records(payload, sort, page)
                    sort_result["records"].extend(records)
                    sort_result["metadata_fields"] = sorted(set(sort_result["metadata_fields"]) | set(metadata_fields))
                    metadata = payload.get("_aMetadata") if isinstance(payload, dict) else None
                    if isinstance(metadata, dict) and page == 1:
                        sort_result["metadata_samples"] = {key: value for key, value in metadata.items()
                                                           if isinstance(value, (str, int, float, bool, type(None)))}
                    request_info["record_count"] = len(records)
                    if failures:
                        request_info["record_failures"] = failures
                if request_info.get("stop_all"):
                    stop_all = True
                    break
                if sort != SORTS[-1] or page != 2:
                    time.sleep(1.0)
            records = sort_result["records"]
            sort_result["page_record_counts"] = [next((r.get("record_count", 0) for r in sort_result["requests"] if r["page"] == p), 0) for p in (1, 2)]
            sort_result["analysis"] = analyze_sort(records)
            sort_result["pagination"] = duplicate_analysis(records)
            sort_result["retrieved_records"] = len(records)
            report["sorts"][sort] = sort_result
            if stop_all:
                break
    report["actual_request_count"] = request_count
    present_sorts = list(report["sorts"])
    report["cross_sort_comparison"] = {
        "unique_ids_by_sort": {sort: report["sorts"][sort]["analysis"]["unique_item_ids"] for sort in present_sorts},
        "all_three_sorts_tested": len(present_sorts) == 3,
        "id_sets_differ": (len(present_sorts) == 3 and len({tuple(report["sorts"][sort]["analysis"]["unique_item_ids"]) for sort in present_sorts}) > 1),
    }
    report["conclusions"] = {
        "sort_semantics": "inconclusive; two-page samples only show observed timestamp order, not contractual sort semantics",
        "thirty_day_boundary": "sample-only observation; does not establish API completeness or a server-side 30-day filter",
        "pagination_completeness": "inconclusive; only two pages per sort were requested",
        "recommended_strategy": "Keep bounded page limits, deduplicate by (source, item_type, item_id), store all three raw timestamps, and revisit older records until a verified stopping rule exists.",
    }
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(report)
    return 0


def print_summary(report: dict[str, Any]) -> None:
    print("GameBanana 原神分页审计摘要")
    for sort, result in report["sorts"].items():
        duplicate = result["pagination"]["cross_page_duplicate_count"]
        print(f"- {sort}: 请求 {len(result['requests'])} 次，记录 {result['retrieved_records']} 条，去重 {result['pagination']['unique_count']} 条，跨页重复 {duplicate} 条")
        print(f"  缺少 _tsDateUpdated：{result['analysis']['missing_updated_count']} 条；旧作品近期明确更新案例：{result['analysis']['old_created_recent_updated_item_ids']}")
        anomalies = [field for field, value in result["analysis"]["time_ordering"].items() if value["status"] == "not_monotonic"]
        print(f"  时间排序异常字段：{anomalies if anomalies else '未观察到/样本不足'}；30 天边界：{result['analysis']['thirty_day_boundary_status']}")
        print(f"  _aMetadata 字段：{result['metadata_fields']}")
    print(f"总请求数：{report['actual_request_count']}；摘要文件：{REPORT_PATH}")
    print(f"建议：{report['conclusions']['recommended_strategy']}")


if __name__ == "__main__":
    raise SystemExit(main())
