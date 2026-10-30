"""Safe, idempotent import of normalized GameBanana sample snapshots."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Iterable


SAMPLE_NAME = re.compile(r"^gamebanana_\d+(?:_\d{8}_\d{6})?\.json$", re.IGNORECASE)
IDENTITY_FIELDS = ("source", "item_type", "item_id")
DB_FIELDS = (
    "game_id", "game_name", "title", "original_url", "author_id", "author_name", "author_url",
    "created_at", "modified_at", "updated_at", "version", "category", "subcategory",
    "tags_json", "preview_urls_json", "content_rating_status", "raw_metadata_json",
)
JSON_FIELDS = {"tags_json", "preview_urls_json", "raw_metadata_json"}
EVENT_FIELDS = (
    "title", "author_id", "author_name", "author_url", "version", "category", "subcategory", "tags_json",
)
EVENT_FIELD_NAMES = {"tags_json": "tags"}


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def identity(record: dict[str, Any]) -> tuple[str, str, int] | None:
    source, item_type, item_id = (record.get(key) for key in IDENTITY_FIELDS)
    if (not isinstance(source, str) or not source.strip()
            or not isinstance(item_type, str) or not item_type.strip()
            or not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0):
        return None
    return source.strip(), item_type.strip(), item_id


def _db_record(record: dict[str, Any], captured_at: datetime | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in DB_FIELDS:
        value = record.get(field)
        if field in ("tags_json", "preview_urls_json"):
            source_key = "tags" if field == "tags_json" else "preview_images"
            value = record.get(source_key)
            if field == "preview_urls_json" and value is None:
                value = record.get("preview_urls")
            if value is not None and not isinstance(value, list):
                value = None
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if value is not None else None
        elif field == "content_rating_status":
            value = value if isinstance(value, str) and value in {"UNKNOWN", "SAFE", "ADULT", "OTHER"} else "UNKNOWN"
        elif field == "raw_metadata_json":
            value = json.dumps({
                "_snapshot_collected_at": captured_at.isoformat().replace("+00:00", "Z") if captured_at else None,
                "_record": record,
            }, ensure_ascii=False, separators=(",", ":"))
        result[field] = value
    return result


def load_sample(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sample_path = Path(path)
    if not SAMPLE_NAME.fullmatch(sample_path.name):
        raise ValueError("Filename is not a recognized GameBanana collector sample name.")
    payload = json.loads(sample_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("game"), dict) or not isinstance(payload.get("records"), list):
        raise ValueError("Expected collector sample object with game and records fields.")
    required_sample_fields = {"collected_at", "days", "requested_max_pages", "pages_requested", "status", "failure_reasons"}
    if not required_sample_fields.issubset(payload):
        raise ValueError("JSON does not contain the collector sample envelope fields.")
    game = payload["game"]
    if not isinstance(game.get("game_id"), int) or isinstance(game.get("game_id"), bool):
        raise ValueError("Sample game.game_id is missing or invalid.")
    captured_at = parse_utc(payload.get("collected_at"))
    return {"path": str(sample_path), "captured_at": captured_at, "captured_at_raw": payload.get("collected_at")}, payload["records"]


def merge_snapshots(snapshots: Iterable[tuple[dict[str, Any], list[dict[str, Any]]]]) -> tuple[dict[tuple[str, str, int], dict[str, Any]], dict[str, Any]]:
    candidates: dict[tuple[str, str, int], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    report = {"files": 0, "input_records": 0, "batch_duplicates": 0, "skipped": 0,
              "errors": 0, "snapshot_warnings": [], "file_errors": []}
    for file_info, records in snapshots:
        report["files"] += 1
        for record in records:
            report["input_records"] += 1
            if not isinstance(record, dict) or identity(record) is None:
                report["skipped"] += 1
                continue
            key = identity(record)
            candidates[key].append((file_info, record))
    merged: dict[tuple[str, str, int], dict[str, Any]] = {}
    for key, versions in candidates.items():
        if len(versions) > 1:
            report["batch_duplicates"] += len(versions) - 1
        dated = [entry for entry in versions if entry[0].get("captured_at") is not None]
        undated = [entry for entry in versions if entry[0].get("captured_at") is None]
        if dated:
            dated.sort(key=lambda entry: (entry[0]["captured_at"], entry[0].get("path", "")))
            newest_time = dated[-1][0]["captured_at"]
            newest = [entry for entry in dated if entry[0]["captured_at"] == newest_time]
            base_info, base_record = newest[-1]
            if len(newest) > 1 and any(entry[1] != base_record for entry in newest[:-1]):
                report["snapshot_warnings"].append({"identity": key, "reason": "Conflicting snapshots have equal collected_at; deterministic filename tie-break used."})
            ordered = dated + undated
            if undated:
                report["snapshot_warnings"].append({"identity": key, "reason": "Undated snapshots used only to fill missing fields; they do not override dated values."})
        else:
            ordered = sorted(versions, key=lambda entry: entry[0].get("path", ""))
            base_info, base_record = ordered[0]
            if len(versions) > 1:
                report["snapshot_warnings"].append({"identity": key, "reason": "No comparable collected_at values; stable filename order used and only missing values are filled."})

        selected = dict(base_record)
        # Start with newest known snapshot and fill only absent values from older/undated snapshots.
        if dated:
            ordered = list(reversed(dated)) + undated
        else:
            ordered = sorted(versions, key=lambda entry: entry[0].get("path", ""))
        for _, older in ordered[1:]:
            for field in DB_FIELDS:
                if _is_missing(selected.get(field)) and not _is_missing(older.get(field)):
                    selected[field] = older[field]
        merged[key] = {"record": _db_record(selected, base_info.get("captured_at")), "captured_at": base_info.get("captured_at")}
    return merged, report


def _is_missing(value: Any) -> bool:
    if value is None or value == "" or value == []:
        return True
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed == []
        except (ValueError, json.JSONDecodeError):
            pass
    return False


def _current_row(connection: sqlite3.Connection, key: tuple[str, str, int]) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM mods WHERE source=? AND item_type=? AND item_id=?", key
    ).fetchone()


def _event_value(field: str, value: Any) -> Any:
    if field == "tags_json" and value is not None:
        try:
            parsed = json.loads(value)
            return sorted(parsed) if isinstance(parsed, list) else parsed
        except (TypeError, json.JSONDecodeError):
            return value
    return value


def _import_locked(connection: sqlite3.Connection, merged: dict[tuple[str, str, int], dict[str, Any]],
                   report: dict[str, Any], dry_run: bool, now: str,
                   before_write: Callable[[], None] | None,
                   sync_run: dict[str, Any] | None) -> dict[str, Any]:
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    event_counts = {"new_events": 0, "metadata_events": 0, "source_update_events": 0}
    plans: list[tuple[str, tuple[str, str, int], dict[str, Any], str, str | None, dict[str, Any] | None, str | None]] = []
    for key, item in merged.items():
        new = item["record"]
        existing = _current_row(connection, key)
        last_checked = item["captured_at"].isoformat(timespec="seconds").replace("+00:00", "Z") if item["captured_at"] else now
        if existing is None:
            counts["inserted"] += 1
            plans.append(("inserted", key, new, last_checked, "first_seen", {}, new.get("created_at")))
            continue
        existing_capture = None
        raw_existing = None
        try:
            raw_existing = json.loads(existing["raw_metadata_json"]) if existing["raw_metadata_json"] else None
            if isinstance(raw_existing, dict):
                existing_capture = parse_utc(raw_existing.get("_snapshot_collected_at"))
        except (TypeError, json.JSONDecodeError):
            existing_capture = None
        incoming_capture = item["captured_at"]
        can_replace = (incoming_capture is not None and existing_capture is not None
                       and incoming_capture > existing_capture)
        if incoming_capture is None or existing_capture is None:
            if incoming_capture is not None or existing_capture is not None:
                report["snapshot_warnings"].append({
                    "identity": key,
                    "reason": "Database/sample collection times are missing or incomparable; existing non-missing values are preserved.",
                })
        elif incoming_capture < existing_capture:
            report["snapshot_warnings"].append({"identity": key, "reason": "Older sample snapshot ignored for existing non-missing values."})
        actual_changes = False
        metadata_changes: dict[str, dict[str, Any]] = {}
        for field in DB_FIELDS:
            incoming = new.get(field)
            current = existing[field]
            missing_incoming = _is_missing(incoming) or (
                field == "content_rating_status" and incoming == "UNKNOWN" and current not in (None, "", "UNKNOWN")
            )
            if missing_incoming or (not can_replace and not _is_missing(current)):
                new[field] = current
            elif field != "raw_metadata_json" and incoming != current:
                actual_changes = True
                if field in EVENT_FIELDS and _event_value(field, current) != _event_value(field, incoming):
                    event_field = EVENT_FIELD_NAMES.get(field, field)
                    metadata_changes[event_field] = {
                        "old": _event_value(field, current),
                        "new": _event_value(field, incoming),
                    }

        # Index snapshots do not include detail rating labels. Preserve the
        # independently verified evidence when refreshing ordinary metadata.
        if isinstance(raw_existing, dict) and isinstance(raw_existing.get("_source_rating_evidence"), dict):
            raw_incoming = json.loads(new["raw_metadata_json"] or "{}")
            raw_incoming["_source_rating_evidence"] = raw_existing["_source_rating_evidence"]
            new["raw_metadata_json"] = json.dumps(raw_incoming, ensure_ascii=False, separators=(",", ":"))

        old_updated = parse_utc(existing["updated_at"])
        new_updated = parse_utc(new.get("updated_at"))
        source_updated = bool(can_replace and old_updated is not None and new_updated is not None
                              and new_updated > old_updated)
        existing_checked = parse_utc(existing["last_checked_at"])
        incoming_checked = parse_utc(last_checked)
        if existing_checked is not None and (incoming_checked is None or incoming_checked < existing_checked):
            last_checked = existing["last_checked_at"]
        status = "updated" if actual_changes else "unchanged"
        counts[status] += 1
        if source_updated:
            event_type = "source_updated"
            event_data = {"source_updated_at": new.get("updated_at")}
            if metadata_changes:
                event_data["metadata_changes"] = metadata_changes
            occurred_at = new.get("updated_at")
        elif metadata_changes:
            event_type = "metadata_changed"
            event_data = {"changes": metadata_changes}
            occurred_at = None
        else:
            event_type, event_data, occurred_at = None, None, None
        plans.append((status, key, new, last_checked, event_type, event_data, occurred_at))

    report.update(counts)
    report["unique_records"] = len(merged)
    report["dry_run"] = dry_run
    if dry_run:
        for _, _, _, _, event_type, _, _ in plans:
            if event_type == "first_seen":
                event_counts["new_events"] += 1
            elif event_type == "metadata_changed":
                event_counts["metadata_events"] += 1
            elif event_type == "source_updated":
                event_counts["source_update_events"] += 1
    if not dry_run:
        write_needed = counts["inserted"] > 0 or counts["updated"] > 0
        if (write_needed or (sync_run is not None and sync_run.get('author_check'))) and before_write is not None:
            before_write()
        if write_needed:
            columns = ", ".join((*IDENTITY_FIELDS, *DB_FIELDS, "first_seen_at", "last_checked_at"))
            placeholders = ", ".join("?" for _ in range(3 + len(DB_FIELDS) + 2))
            updates = ", ".join(
                f"{field}=COALESCE(excluded.{field}, mods.{field})" for field in DB_FIELDS
            ) + ", last_checked_at=excluded.last_checked_at"
            statement = (
                f"INSERT INTO mods ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(source, item_type, item_id) DO UPDATE SET {updates}"
            )
            for status, key, record, last_checked, event_type, event_data, occurred_at in plans:
                if status != "unchanged":
                    values = (*key, *(record[field] for field in DB_FIELDS), now, last_checked)
                    connection.execute(statement, values)
                if status == "inserted":
                    connection.execute(
                        "INSERT INTO user_states (source,item_type,item_id,updated_at) VALUES (?,?,?,?) "
                        "ON CONFLICT(source,item_type,item_id) DO NOTHING",
                        (*key, now),
                    )
                if event_type is not None:
                    exists = connection.execute(
                        "SELECT 1 FROM mod_events WHERE source=? AND item_type=? AND item_id=? AND event_type=? "
                        "AND occurred_at IS ? AND event_data_json IS ? LIMIT 1",
                        (*key, event_type, occurred_at,
                         json.dumps(event_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
                    ).fetchone()
                    if exists is None:
                        connection.execute(
                            "INSERT INTO mod_events (source,item_type,item_id,event_type,occurred_at,detected_at,event_data_json) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (*key, event_type, occurred_at, now,
                             json.dumps(event_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
                        )
                        if event_type == "first_seen":
                            event_counts["new_events"] += 1
                        elif event_type == "metadata_changed":
                            event_counts["metadata_events"] += 1
                        elif event_type == "source_updated":
                            event_counts["source_update_events"] += 1
        if sync_run is not None:
            error_summary = {
                **({'web_sync': sync_run['web_sync']} if sync_run.get('web_sync') else {}),
                **({'author_check': sync_run['author_check']} if sync_run.get('author_check') else {}),
                "scan_errors": sync_run.get("errors", []),
                "inserted": counts["inserted"],
                "updated": counts["updated"],
                "unchanged": counts["unchanged"],
                "new_events": event_counts["new_events"],
                "metadata_events": event_counts["metadata_events"],
                "source_update_events": event_counts["source_update_events"],
            }
            cursor = connection.execute(
                "INSERT INTO sync_runs (source,game_id,started_at,ended_at,status,request_count,fetched_count,deduplicated_count,error_summary) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (sync_run["source"], sync_run["game_id"], sync_run["started_at"],
                 sync_run["ended_at"], sync_run["status"], sync_run["request_count"],
                 sync_run["fetched_count"], sync_run["deduplicated_count"],
                 json.dumps(error_summary, ensure_ascii=False, separators=(",", ":"))),
            )
            report["sync_run_id"] = cursor.lastrowid
    report.update(event_counts)
    report["database_total"] = connection.execute("SELECT COUNT(*) FROM mods").fetchone()[0]
    report["errors"] = report.get("errors", 0) + len(report["file_errors"])
    return report


def import_samples(connection: sqlite3.Connection, snapshots: Iterable[tuple[dict[str, Any], list[dict[str, Any]]]],
                   dry_run: bool = True, now: str | None = None,
                   before_write: Callable[[], None] | None = None,
                   sync_run: dict[str, Any] | None = None, precondition=None) -> dict[str, Any]:
    merged, report = merge_snapshots(snapshots)
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if dry_run:
        return _import_locked(connection, merged, report, True, now, None, None)

    # Keep the change decision, backup, and writes serialized under the same write lock.
    connection.execute("BEGIN IMMEDIATE")
    try:
        if precondition is not None:
            precondition(connection)
        result = _import_locked(connection, merged, report, False, now, before_write, sync_run)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise

