"""Validate small samples from GameBanana public detail and index APIs."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
GAMES_FILE = ROOT / "config" / "games.json"
REPORT_FILE = ROOT / "logs" / "probe_details_report.json"
TIMEOUT = httpx.Timeout(15.0, connect=8.0)
HEADERS = {"User-Agent": "ErYouToolbox/0.1 public-api-feasibility-probe"}
DELAY_SECONDS = 1.0
MAX_RETRIES = 1


class ProbeError(Exception):
    def __init__(self, message: str, meta: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.meta = meta or {}


def get_json(client: httpx.Client, url: str, params: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """GET JSON with one retry for transient network/server errors; stop on 429."""
    attempt = 0
    while True:
        try:
            response = client.get(url, params=params)
            result_meta = {
                "url": str(response.request.url),
                "http_status": response.status_code,
                "content_type": response.headers.get("Content-Type"),
            }
            print(f"  HTTP {response.status_code}: {response.request.url}")
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_seconds = max(0.0, min(float(retry_after), 120.0))
                    except ValueError:
                        wait_seconds = 0.0
                    if wait_seconds:
                        print(f"  收到 429，等待 Retry-After 的 {wait_seconds:g} 秒后停止。")
                        time.sleep(wait_seconds)
                raise ProbeError("HTTP 429：按限流要求停止后续请求。", result_meta)
            response.raise_for_status()
            try:
                return response.json(), result_meta
            except (ValueError, json.JSONDecodeError) as exc:
                body_prefix = response.content[:512].lstrip().lower()
                result_meta.update({
                    "response_bytes": len(response.content),
                    "response_empty": len(response.content) == 0,
                    "json_parse_error": str(exc),
                    "suspected_html": body_prefix.startswith(b"<!doctype html") or body_prefix.startswith(b"<html"),
                })
                raise ProbeError(f"响应不是有效 JSON：{exc}", result_meta) from exc
        except ProbeError:
            raise
        except httpx.HTTPStatusError as exc:
            if attempt < MAX_RETRIES and exc.response.status_code >= 500:
                attempt += 1
                time.sleep(2.0)
                continue
            raise ProbeError(f"HTTP 错误：{exc.response.status_code}", {
                "url": str(exc.request.url), "http_status": exc.response.status_code,
            }) from exc
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            if attempt < MAX_RETRIES:
                attempt += 1
                time.sleep(2.0)
                continue
            raise ProbeError(f"网络请求失败：{type(exc).__name__}: {exc}", {"http_status": None}) from exc


def safe_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def sample_mod_ids(value: Any, limit: int = 2) -> list[int]:
    """Extract genuine IDs from Core/List/New rows shaped as [itemtype, itemid]."""
    ids: list[int] = []
    if not isinstance(value, list):
        return ids
    for row in value:
        if (isinstance(row, list) and len(row) == 2 and isinstance(row[0], str)
                and isinstance(row[1], int) and not isinstance(row[1], bool)
                and row[0].lower() == "mod" and row[1] > 0):
            if row[1] not in ids:
                ids.append(row[1])
            if len(ids) >= limit:
                break
    return ids


def parse_allowed_fields(value: Any) -> list[str]:
    """Accept field names only from the live AllowedFields response."""
    fields: list[str] = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str):
                fields.append(entry)
            elif isinstance(entry, list) and entry and isinstance(entry[0], str):
                fields.append(entry[0])
    elif isinstance(value, dict):
        fields.extend(str(key) for key in value)
    return fields


def select_detail_fields(fields: list[str]) -> list[str]:
    """Select semantically relevant names only when present in AllowedFields."""
    groups = {
        "title": ("name", "title"),
        "url": ("url", "profileurl", "websiteurl"),
        "author": ("owner", "submitter", "author", "creator"),
        "created": ("dateadded", "datecreated", "created"),
        "modified": ("datemodified", "dateupdated", "modified", "updated"),
        "update_info": ("description", "text", "updates", "changelog"),
        "preview": ("preview", "thumbnail", "image"),
        "category": ("category",),
        "content_rating": ("nsfw", "adult", "contentrating", "contentratings"),
        "files": ("files", "filedata", "filecount"),
    }
    lowered = [(field, field.lower().replace("_", "")) for field in fields]
    selected: list[str] = []
    for fragments in groups.values():
        matches = [field for field, normalized in lowered
                   if any(fragment.replace("_", "") in normalized for fragment in fragments)]
        for field in matches[:2]:
            if field not in selected:
                selected.append(field)
    return selected[:24]


def detail_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "response_type": "dict",
            "fields": {str(key): safe_value_type(item) for key, item in value.items()},
            "empty_fields": [str(key) for key, item in value.items() if item is None or item == "" or item == []],
        }
    if isinstance(value, list):
        return {
            "response_type": "list",
            "field_types": [safe_value_type(item) for item in value],
            "empty_positions": [index for index, item in enumerate(value) if item is None or item == "" or item == []],
        }
    return {"response_type": safe_value_type(value), "diagnostic": "Unexpected detail response shape."}


def summarize_index(value: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"response_type": safe_value_type(value)}
    if not isinstance(value, dict):
        summary["diagnostic"] = "Expected JSON object with _aRecords and _aMetadata."
        return summary
    summary["top_level_keys"] = list(value.keys())[:30]
    records = value.get("_aRecords")
    metadata = value.get("_aMetadata")
    summary["has_aRecords"] = "_aRecords" in value
    summary["has_aMetadata"] = "_aMetadata" in value
    summary["metadata_type"] = safe_value_type(metadata)
    summary["record_count"] = len(records) if isinstance(records, list) else None
    if isinstance(records, list):
        summary["record_types"] = [safe_value_type(record) for record in records[:5]]
        sample_checks = []
        sample_rating_fields: list[str] = []
        if records and isinstance(records[0], dict):
            summary["record_fields"] = {str(key): safe_value_type(item) for key, item in records[0].items()}
            summary["record_sample"] = {
                str(key): (str(item)[:100] if isinstance(item, str) else item)
                for key, item in records[0].items()
                if key in {"_idRow", "_sName", "_sProfileUrl", "_sSubmitter", "_tsDateAdded",
                           "_tsDateModified", "_tsDateUpdated", "_sModelName"}
            }
        for row in records[:5]:
            game = row.get("_aGame") if isinstance(row, dict) else None
            game_id = game.get("_idRow") if isinstance(game, dict) else None
            sample_checks.append({
                "mod_id": row.get("_idRow") if isinstance(row, dict) else None,
                "game_id": game_id,
                "filter_status": "unknown" if game_id is None else ("match" if str(game_id) == "8552" else "mismatch"),
            })
            if isinstance(row, dict):
                sample_rating_fields.extend(key for key in row if "rating" in key.lower() and key not in sample_rating_fields)
        known_game_ids = [item["game_id"] for item in sample_checks if item["game_id"] is not None]
        summary["sample_records"] = sample_checks
        summary["sample_filter_verified"] = (
            len(sample_checks) == 5 and len(known_game_ids) == 5 and all(str(value) == "8552" for value in known_game_ids)
        )
        summary["sample_filter_status"] = (
            "verified" if summary["sample_filter_verified"] else
            "unknown" if not known_game_ids else "not_verified"
        )
        summary["content_rating_fields"] = sample_rating_fields
    return summary


def error_report(exc: ProbeError) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), **exc.meta}


def main() -> int:
    report: dict[str, Any] = {
        "scope": "Small public API structure probe; no image/file downloads.",
        "requests": {},
        "conclusions": {},
        "unverified": [
            "Date semantics require API documentation or independent confirmation.",
            "Content rating safety cannot be inferred from absent/false rating flags.",
            "Only one apiv11 page was requested; full-list pagination was not tested.",
        ],
    }
    try:
        games = json.loads(GAMES_FILE.read_text(encoding="utf-8"))["games"]
        game = next(item for item in games if item.get("game_id") == 8552)
    except Exception as exc:
        report["configuration_error"] = str(exc)
        write_report(report)
        print(f"读取游戏配置失败：{exc}")
        return 1

    REPORT_FILE.parent.mkdir(exist_ok=True)
    print("GameBanana 详情与 apiv11 小样本验证")
    stop = False
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        try:
            allowed, meta = get_json(client, "https://api.gamebanana.com/Core/Item/Data/AllowedFields",
                                     {"itemtype": "Mod"})
            fields = parse_allowed_fields(allowed)
            selected_fields = select_detail_fields(fields)
            report["requests"]["allowed_fields"] = {
                "ok": True, **meta, "response_type": safe_value_type(allowed),
                "field_count": len(fields), "field_names": fields[:200],
                "selected_actual_fields": selected_fields,
            }
            print(f"AllowedFields：成功，获得 {len(fields)} 个字段；选择 {len(selected_fields)} 个实际字段。")
        except ProbeError as exc:
            report["requests"]["allowed_fields"] = error_report(exc)
            fields, selected_fields = [], []
            print(f"AllowedFields：失败，{exc}")
            stop = "429" in str(exc)

        if not stop and selected_fields:
            # Fixed real IDs from the previous probe allow a minimal A/B comparison.
            ids = [732435, 732221]
            report["requests"]["detail_comparison"] = {
                "mod_ids": ids,
                "fields": ["name", "date", "mdate", "udate"],
                "field_names_confirmed_by_allowed_fields": all(
                    field in fields for field in ("name", "date", "mdate", "udate")
                ),
            }
            if report["requests"]["detail_comparison"]["field_names_confirmed_by_allowed_fields"]:
                for mod_id in ids:
                    time.sleep(DELAY_SECONDS)
                    try:
                        value, meta = get_json(client, "https://api.gamebanana.com/Core/Item/Data", {
                            "itemtype": "Mod", "itemid": mod_id,
                            "fields": "name,date,mdate,udate", "return_keys": 1,
                        })
                        summary = detail_summary(value)
                        report["requests"][f"detail_{mod_id}"] = {"ok": True, **meta, **summary}
                        print(f"详情 {mod_id}：成功，返回结构 {summary['response_type']}。")
                    except ProbeError as exc:
                        report["requests"][f"detail_{mod_id}"] = error_report(exc)
                        print(f"详情 {mod_id}：失败，{exc}")
                        if "429" in str(exc):
                            stop = True
                            break
            else:
                report["requests"]["detail_note"] = "One or more minimal field names were absent from AllowedFields."
        elif not selected_fields:
            report["requests"]["detail_note"] = "No confirmed AllowedFields names available; detail requests skipped."

        if not stop:
            time.sleep(DELAY_SECONDS)
            try:
                index, meta = get_json(client, "https://gamebanana.com/apiv11/Mod/Index", {
                    "_nPage": 1,
                    "_nPerpage": 5,
                    "_aFilters[Generic_Game]": 8552,
                    "_sSort": "Generic_NewAndUpdated",
                })
                summary = summarize_index(index)
                report["requests"]["apiv11_index"] = {"ok": True, **meta, **summary}
                records = index.get("_aRecords") if isinstance(index, dict) else None
                report["requests"]["apiv11_index"]["sample_filter_status"] = summary.get("sample_filter_status", "unknown")
                print(f"apiv11：成功，JSON 类型 {summary['response_type']}，记录数 {summary.get('record_count')}，样本过滤状态 {summary.get('sample_filter_status', 'unknown')}。")
            except ProbeError as exc:
                report["requests"]["apiv11_index"] = error_report(exc)
                print(f"apiv11：失败，{exc}")

    detail_entries = [value for key, value in report["requests"].items() if key.startswith("detail_") and value.get("ok")]
    index_result = report["requests"].get("apiv11_index", {})
    report["conclusions"] = {
        "core_item_data_available": bool(detail_entries),
        "successful_mod_ids": [int(key.removeprefix("detail_")) for key, value in report["requests"].items()
                                if key.startswith("detail_") and value.get("ok")],
        "apiv11_game_filter_sample_verified": index_result.get("sample_filter_verified", False),
        "apiv11_game_filter_sample_status": index_result.get("sample_filter_status", "unknown"),
        "apiv11_game_filter_supported": index_result.get("sample_filter_verified", False),
        # One page proves paginated records are returned; it does not prove a full listing.
        "apiv11_full_list_available": False,
        "apiv11_page_records_available": bool(index_result.get("ok") and index_result.get("has_aRecords")),
        "new_update_identification_fields": [field for field in fields
            if any(word in field.lower() for word in ("date", "updated", "modified", "revision"))],
        "nsfw_safe_filtering": "insufficient; use UNKNOWN unless a reliable explicit rating value is observed",
        "sqlite_priority_fields": ["item_id", "item_type", "title", "profile_url", "author_id/name",
            "date_added_raw", "date_modified_raw", "date_updated_raw", "category_id/name",
            "content_rating_raw", "rating_confidence", "preview_url", "last_checked_at"],
        "detail_fields": ["name", "date", "mdate", "udate"],
        "apiv11_direct_metadata": ["_idRow", "_sName", "_sProfileUrl", "_tsDateAdded", "_tsDateModified", "_aSubmitter", "_aPreviewMedia", "_aRootCategory", "_aSubCategory", "_aTags", "_aGame"],
        "fields_requiring_detail_api": ["description", "update history/details", "file metadata", "explicit NSFW value", "some author/category details"],
        "formal_collector_ready": False,
        "formal_collector_readiness_reason": "API structures are partly validated, but pagination semantics, update timestamp meaning, reliable rating policy, and error cases still need decisions before collection design.",
    }
    write_report(report)
    print("\n简要结论：")
    print(f"- Core/Item/Data：{'可用' if report['conclusions']['core_item_data_available'] else '未确认可用'}；成功详情 ID：{report['conclusions']['successful_mod_ids']}")
    print(f"- apiv11 游戏过滤样本：{report['conclusions']['apiv11_game_filter_sample_status']}；单页结果不代表所有分页。")
    print(f"- 新增/更新候选字段：{report['conclusions']['new_update_identification_fields']}")
    print("- NSFW：分级不足以安全筛选；无可靠依据的作品应标记 UNKNOWN。")
    print(f"- 详细摘要：{REPORT_FILE}")
    return 0


def write_report(report: dict[str, Any]) -> None:
    try:
        REPORT_FILE.parent.mkdir(exist_ok=True)
        REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"报告写入失败：{exc}")


if __name__ == "__main__":
    raise SystemExit(main())
