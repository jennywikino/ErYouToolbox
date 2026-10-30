"""Small bounded GameBanana apiv11 Mod index collector."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import time
from typing import Any

import httpx

from .models import normalize_record


API_URL = "https://gamebanana.com/apiv11/Mod/Index"
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
HEADERS = {"User-Agent": "ErYouToolbox/0.1 bounded public metadata collector"}
MAX_PER_PAGE = 50


def inspect_pagination(requested: int, page: int, row_count: int,
                       metadata: Any) -> dict[str, Any]:
    """Classify short pages without treating them alone as a failure or completion."""
    result = {"page": page, "requested_per_page": requested, "returned_count": row_count,
              "metadata_per_page": None, "record_count": None,
              "server_page_limit": False, "end_of_results": False,
              "classification": "unknown_metadata", "error": None}
    if not isinstance(metadata, dict):
        return result
    actual = metadata.get("_nPerpage")
    total = metadata.get("_nRecordCount")
    if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
        result["record_count"] = total
    if "_nPerpage" not in metadata:
        return result
    if not isinstance(actual, int) or isinstance(actual, bool) or actual < 1:
        result.update(classification="abnormal_response",
                      error="_aMetadata._nPerpage is missing or invalid.")
        return result
    result["metadata_per_page"] = actual
    result["server_page_limit"] = actual < requested
    if actual > requested or row_count > actual:
        result.update(classification="abnormal_response",
                      error="Returned pagination size conflicts with the request or metadata.")
        return result
    if result["record_count"] is not None:
        expected = min(actual, max(0, result["record_count"] - (page - 1) * actual))
        if row_count != expected:
            result.update(classification="abnormal_response",
                          error=f"Expected {expected} records from pagination metadata, got {row_count}.")
            return result
        if expected < actual:
            result.update(classification="normal_last_page", end_of_results=True)
            return result
    elif row_count < actual:
        result["classification"] = "short_page_unconfirmed"
        return result
    result["classification"] = "server_page_limit" if actual < requested else "full_page"
    return result


class CollectionError(Exception):
    pass


def deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any, Any]] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        key = (record.get("source"), record.get("item_type"), record.get("item_id"))
        if key not in seen:
            seen.add(key)
            unique.append(record)
    return unique


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def collect_game(client: httpx.Client, game: dict[str, Any], days: int = 30,
                 max_pages: int = 1, per_page: int = 10, delay: float = 1.0,
                 sort: str = "Generic_NewAndUpdated", start_page: int = 1) -> dict[str, Any]:
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if type(start_page) is not int or start_page < 1:
        raise ValueError("start_page must be a positive integer")
    if not 1 <= per_page <= MAX_PER_PAGE:
        raise ValueError(f"per_page must be between 1 and {MAX_PER_PAGE}")
    game_id = game["game_id"]
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    page_count = 0
    request_count = 0
    hit_rate_limit = False
    metadata_summary: Any = None
    pagination_pages: list[dict[str, Any]] = []
    cutoff = int(time.time()) - max(days, 0) * 86400

    for page in range(start_page, start_page + max_pages):
        params = {
            "_nPage": page,
            "_nPerpage": per_page,
            "_aFilters[Generic_Game]": game_id,
            "_sSort": sort,
        }
        attempt = 0
        while True:
            try:
                request_count += 1
                response = client.get(API_URL, params=params)
                page_count += 1
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait_seconds = _retry_after_seconds(retry_after)
                    failures.append({"page": page, "http_status": 429,
                                     "reason": "HTTP 429; Retry-After missing or invalid, collection stopped." if wait_seconds is None else f"HTTP 429; waited {wait_seconds:g}s then stopped."})
                    if wait_seconds is not None:
                        time.sleep(wait_seconds)
                    hit_rate_limit = True
                    break
                response.raise_for_status()
                try:
                    payload = response.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    failures.append({"page": page, "http_status": response.status_code,
                                     "reason": f"Invalid JSON: {exc}"})
                    payload = None
                if isinstance(payload, dict):
                    rows = payload.get("_aRecords")
                    metadata = payload.get("_aMetadata")
                    if isinstance(rows, list):
                        pagination = inspect_pagination(per_page, page, len(rows), metadata)
                        pagination_pages.append(pagination)
                        if pagination.get("error"):
                            failures.append({"page": page, "http_status": response.status_code,
                                             "reason": pagination["error"]})
                        for row in rows:
                            if not isinstance(row, dict):
                                failures.append({"page": page, "reason": "Record is not an object."})
                                continue
                            row_game_id = row.get("_aGame", {}).get("_idRow") if isinstance(row.get("_aGame"), dict) else None
                            if row_game_id != game_id:
                                failures.append({"page": page, "item_id": row.get("_idRow"),
                                                 "reason": "Missing or mismatched _aGame._idRow.",
                                                 "observed_game_id": row_game_id})
                                continue
                            normalized = normalize_record(row, game)
                            # Candidate activity time is retained separately; modified_at is not proof of a version update.
                            raw_times = [row.get(key) for key in ("_tsDateAdded", "_tsDateModified", "_tsDateUpdated")]
                            numeric_times = [value for value in raw_times if isinstance(value, int) and not isinstance(value, bool)]
                            normalized["activity_time_candidate"] = max(numeric_times) if numeric_times else None
                            normalized["within_days_candidate"] = (normalized["activity_time_candidate"] >= cutoff
                                                                      if normalized["activity_time_candidate"] is not None else None)
                            records.append(normalized)
                    else:
                        failures.append({"page": page, "reason": "JSON object has no list _aRecords."})
                        pagination_pages.append({"page": page, "classification": "abnormal_response",
                                                 "error": "JSON object has no list _aRecords."})
                    # Keep only bounded paging metadata, excluding record payloads.
                    metadata_summary = metadata if isinstance(metadata, dict) else None
                else:
                    failures.append({"page": page, "reason": f"Expected JSON object, got {type(payload).__name__}."})
                    metadata_summary = None
                break
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if attempt == 0 and (status is None or status >= 500):
                    attempt += 1
                    time.sleep(1.0)
                    continue
                failures.append({"page": page, "http_status": status,
                                 "reason": f"{type(exc).__name__}: {exc}"})
                metadata_summary = None
                break

        if hit_rate_limit:
            break
        if pagination_pages and pagination_pages[-1].get("end_of_results"):
            break
        if page < start_page + max_pages - 1:
            time.sleep(delay)

    unique = deduplicate(records)
    # The sort/update semantics and time-window termination condition are not established.
    complete = False
    return {
        "game": game,
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "days": days,
        "requested_max_pages": max_pages,
        "pages_requested": page_count,
        "request_count": request_count,
        "per_page": per_page,
        "actual_record_count": len(records),
        "deduplicated_count": len(unique),
        "complete_for_time_window": complete,
        "status": "incomplete" if failures or page_count >= max_pages else "partial",
        "failure_reasons": failures,
        "records": unique,
        "pagination_metadata": metadata_summary,
        "pagination_pages": pagination_pages,
        "notes": ["modified_at is not treated as proof of a version update.",
                  "updated_at is null when the API does not provide _tsDateUpdated.",
                  "All unknown content ratings remain UNKNOWN.",
                  "Time-window filtering is a candidate only; old creations are retained when recent modified/updated timestamps are present.",
                  "Completeness is unverified because sort and page termination semantics are not proven."],
    }
