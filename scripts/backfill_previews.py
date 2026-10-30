"""Bounded, ID-matched backfill of GameBanana preview URLs for existing MODs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eryoutoolbox.database import backup_database  # noqa: E402
from eryoutoolbox.gamebanana import (API_URL, HEADERS, MAX_PER_PAGE, TIMEOUT,
                                     _retry_after_seconds, deduplicate,
                                     inspect_pagination)  # noqa: E402
from eryoutoolbox.models import extract_preview_images, normalize_record, valid_image_url  # noqa: E402
from probe_preview_quality import find_preview_media  # noqa: E402

MAX_PAGES_PER_RUN = 20
CHECKPOINT_FORMAT = "eryoutoolbox-preview-backfill-v1"
SOURCE = "gamebanana"
ITEM_TYPE = "Mod"
_GB_VARIANT = re.compile(r"^\d+-\d+_(.+)$")
PROFILE_API_TEMPLATE = "https://gamebanana.com/apiv11/Mod/{item_id}/ProfilePage"


def load_games(path: str | Path = ROOT / "config" / "games.json") -> list[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        games = payload["games"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Cannot load game configuration: {exc}") from exc
    if not isinstance(games, list) or not games:
        raise ValueError("config/games.json must contain a non-empty games list.")
    result: list[dict[str, Any]] = []
    ids: set[int] = set()
    for game in games:
        if (not isinstance(game, dict) or not isinstance(game.get("name"), str)
                or not isinstance(game.get("game_id"), int)
                or isinstance(game.get("game_id"), bool) or game["game_id"] <= 0
                or game["game_id"] in ids):
            raise ValueError("Each configured game needs a unique positive integer game_id and name.")
        ids.add(game["game_id"])
        result.append({"name": game["name"], "game_id": game["game_id"]})
    return result


GAMES = load_games()
GAMES_BY_ID = {game["game_id"]: game for game in GAMES}
GAME = GAMES_BY_ID[19567]
LEGACY_GAME = GAMES_BY_ID[8552]


def _asset_key(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    parent, _, filename = unquote(parsed.path).rpartition("/")
    match = _GB_VARIANT.fullmatch(filename)
    if match:
        filename = match.group(1)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parent}", filename


def _is_thumbnail_url(url: Any) -> bool:
    if not valid_image_url(url):
        return False
    filename = unquote(urlsplit(url).path.rpartition("/")[2])
    return _GB_VARIANT.fullmatch(filename) is not None


def open_existing_database(path: str | Path, *, read_only: bool = True) -> sqlite3.Connection:
    """Open an existing DB without creating files or changing journal settings."""
    database_path = Path(path).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {database_path}")
    if read_only:
        connection = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True, timeout=5.0)
        connection.execute("PRAGMA query_only = ON")
    else:
        connection = sqlite3.connect(database_path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _stored_images(value: Any) -> list[dict[str, str]]:
    try:
        urls = json.loads(value) if isinstance(value, str) else []
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(urls, list):
        return []
    images: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in urls:
        if isinstance(item, str):
            image = {"image_url": item, "thumbnail_url": item, "switch_url": item}
        elif isinstance(item, dict):
            original = item.get("image_url")
            thumbnail = item.get("thumbnail_url")
            switch = item.get("switch_url")
            if not valid_image_url(original):
                continue
            image = {
                "image_url": original,
                "thumbnail_url": thumbnail if valid_image_url(thumbnail) else original,
                "switch_url": switch if valid_image_url(switch) else (
                    thumbnail if valid_image_url(thumbnail) else original),
            }
        else:
            continue
        key = _asset_key(image["image_url"])
        if valid_image_url(image["image_url"]) and key not in seen:
            seen.add(key)
            images.append(image)
    return images


def _has_original_metadata(value: Any) -> bool:
    """Legacy strings are high-resolution candidates only when not a known GB variant."""
    try:
        parsed = json.loads(value) if isinstance(value, str) else []
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(parsed, list):
        return False
    for item in parsed:
        if isinstance(item, str) and valid_image_url(item) and not _is_thumbnail_url(item):
            return True
        if (isinstance(item, dict) and valid_image_url(item.get("image_url"))
                and not _is_thumbnail_url(item["image_url"])):
            return True
    return False


def _is_rich_storage(value: Any) -> bool:
    try:
        parsed = json.loads(value) if isinstance(value, str) else []
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(parsed, list) and any(isinstance(item, dict) for item in parsed)


def fetch_exact_item(client: Any, item_id: int,
                     game: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch one ID-addressed ProfilePage and accept only URLs sourced from _sFile."""
    target_game = game or LEGACY_GAME
    try:
        response = client.get(PROFILE_API_TEMPLATE.format(item_id=item_id))
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            wait = _retry_after_seconds(retry_after)
            reason = ("HTTP 429; no retry was sent" if wait is None
                      else f"HTTP 429; stopped after honoring Retry-After requirement ({wait:g}s)")
            return {"records": [], "request_count": 1,
                    "failure_reasons": [{"reason": reason}], "image_count": 0,
                    "verified_original_count": 0}
        response.raise_for_status()
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            return {"records": [], "request_count": 1,
                    "failure_reasons": [{"reason": f"Invalid JSON: {exc}"}],
                    "image_count": 0, "verified_original_count": 0}
    except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        return {"records": [], "request_count": 1,
                "failure_reasons": [{"http_status": status,
                                     "reason": f"{type(exc).__name__}: {exc}"}],
                "image_count": 0, "verified_original_count": 0}

    media = find_preview_media(payload)
    if media is None:
        return {"records": [], "request_count": 1,
                "failure_reasons": [{"reason": "Response did not contain _aPreviewMedia._aImages."}],
                "image_count": 0, "verified_original_count": 0}
    entries = media.get("_aImages")
    entries = entries if isinstance(entries, list) else []
    images: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        extracted = extract_preview_images({
            "_sBaseUrl": media.get("_sBaseUrl"),
            "_aImages": [entry],
        })
        if extracted and extracted[0].get("original_verified") is True:
            images.append(extracted[0])
    record = {
        "source": SOURCE,
        "item_type": ITEM_TYPE,
        "item_id": item_id,
        "game_id": target_game["game_id"],
        "preview_images": images,
        "preview_urls": list(dict.fromkeys(image["thumbnail_url"] for image in images)),
    }
    return {"records": [record], "request_count": 1, "failure_reasons": [],
            "image_count": len(entries), "verified_original_count": len(images)}


def collect_preview_pages(client: Any, game: dict[str, Any], *, start_page: int = 1,
                          max_pages: int = 1, per_page: int = 50,
                          delay: float = 1.0) -> dict[str, Any]:
    """Collect bounded pages, stopping at the first unsafe or abnormal response."""
    if start_page < 1:
        raise ValueError("start_page must be at least 1")
    if not 1 <= max_pages <= MAX_PAGES_PER_RUN:
        raise ValueError(f"max_pages must be between 1 and {MAX_PAGES_PER_RUN}")
    if not 1 <= per_page <= MAX_PER_PAGE:
        raise ValueError(f"per_page must be between 1 and {MAX_PER_PAGE}")

    records: list[dict[str, Any]] = []
    page_results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    failed_pages: list[int] = []
    requests = 0
    raw_count = 0
    next_page = start_page
    exhausted = False
    stopped_for_rate_limit = False

    for page in range(start_page, start_page + max_pages):
        page_error: dict[str, Any] | None = None
        page_rows: list[dict[str, Any]] = []
        page_raw_count = 0
        page_metadata: dict[str, Any] | None = None
        pagination: dict[str, Any] | None = None
        status_code: int | None = None

        for attempt in range(2):
            params = {
                "_nPage": page,
                "_nPerpage": per_page,
                "_aFilters[Generic_Game]": game["game_id"],
                "_sSort": "Generic_Newest",
            }
            requests += 1
            try:
                response = client.get(API_URL, params=params)
                status_code = response.status_code
                if status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait_seconds = _retry_after_seconds(retry_after)
                    page_error = {
                        "page": page, "http_status": status_code,
                        "retry_after": retry_after,
                        "retry_after_seconds": wait_seconds,
                        "reason": "HTTP 429; stopped this scan without another request.",
                    }
                    stopped_for_rate_limit = True
                    break
                if status_code >= 500 and attempt == 0:
                    time.sleep(1.0)
                    continue
                response.raise_for_status()
                try:
                    payload = response.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    page_error = {"page": page, "http_status": status_code,
                                  "reason": f"Invalid JSON response: {exc}"}
                    break
                if not isinstance(payload, dict) or not isinstance(payload.get("_aRecords"), list):
                    page_error = {"page": page, "http_status": status_code,
                                  "reason": "Expected a JSON object containing list _aRecords."}
                    break

                rows = payload["_aRecords"]
                page_raw_count = len(rows)
                page_metadata = payload.get("_aMetadata") if isinstance(payload.get("_aMetadata"), dict) else None
                pagination = inspect_pagination(per_page, page, page_raw_count, page_metadata)
                if pagination.get("classification") == "abnormal_response":
                    page_error = {"page": page, "http_status": status_code,
                                  "reason": pagination.get("error") or "Abnormal pagination metadata."}
                    break

                for row_index, row in enumerate(rows):
                    if not isinstance(row, dict):
                        page_error = {"page": page, "http_status": status_code,
                                      "reason": f"Record {row_index} is not a JSON object."}
                        break
                    row_game = row.get("_aGame")
                    row_game_id = row_game.get("_idRow") if isinstance(row_game, dict) else None
                    if row_game_id != game["game_id"]:
                        page_error = {"page": page, "http_status": status_code,
                                      "item_id": row.get("_idRow"),
                                      "reason": "Missing or mismatched _aGame._idRow; stopped safely."}
                        continue
                    normalized = normalize_record(row, game)
                    if normalized.get("item_type") != ITEM_TYPE or not normalized.get("item_id"):
                        page_error = {"page": page, "http_status": status_code,
                                      "item_id": row.get("_idRow"),
                                      "reason": "Record has a missing or invalid MOD identity."}
                        continue
                    page_rows.append(normalized)

                if page_error is None:
                    break
                # Keep valid records from this page; the checkpoint will retry this page.
                break
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else status_code
                if attempt == 0 and (status is None or status >= 500):
                    time.sleep(1.0)
                    continue
                page_error = {"page": page, "http_status": status,
                              "reason": f"{type(exc).__name__}: {exc}"}
                break

        raw_count += page_raw_count
        if page_rows:
            records.extend(page_rows)
        page_results.append({
            "page": page, "http_status": status_code,
            "raw_records": page_raw_count,
            "accepted_records": len(page_rows),
            "metadata_fields": list(page_metadata.keys())[:30] if page_metadata else [],
            "pagination": pagination,
        })
        if page_error:
            failures.append(page_error)
            if page not in failed_pages:
                failed_pages.append(page)
            next_page = page
            break

        next_page = page + 1
        if page_raw_count == 0 or (pagination and pagination.get("end_of_results")):
            exhausted = True
            break
        if page < start_page + max_pages - 1:
            time.sleep(max(0.0, delay))
        if stopped_for_rate_limit:
            break

    return {
        "records": deduplicate(records),
        "raw_record_count": raw_count,
        "pages_scanned": len(page_results),
        "pages_requested": len(page_results),
        "request_count": requests,
        "page_results": page_results,
        "failed_pages": failed_pages,
        "failure_reasons": failures,
        "next_page": next_page,
        "exhausted": exhausted,
        "rate_limited": stopped_for_rate_limit,
    }


def resolve_project_file(value: str | Path) -> Path:
    path = Path(value)
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Checkpoint and report files must remain inside the project root.")
    return path


def load_checkpoint(path: str | Path, game: dict[str, Any], *, required: bool = False) -> dict[str, Any] | None:
    checkpoint_path = resolve_project_file(path)
    if not checkpoint_path.exists():
        if required:
            raise FileNotFoundError(f"Checkpoint does not exist: {checkpoint_path}")
        return None
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read checkpoint {checkpoint_path}: {exc}") from exc
    if (not isinstance(payload, dict) or payload.get("format") != CHECKPOINT_FORMAT
            or payload.get("game_id") != game["game_id"]
            or not isinstance(payload.get("next_page"), int)
            or payload["next_page"] < 1):
        raise ValueError("Checkpoint format or game identity is invalid; it was not changed.")
    if ("apply_next_page" in payload and
            (not isinstance(payload["apply_next_page"], int) or payload["apply_next_page"] < 1)):
        raise ValueError("Checkpoint apply_next_page is invalid; it was not changed.")
    return payload


def save_checkpoint(path: str | Path, checkpoint: dict[str, Any]) -> None:
    checkpoint_path = resolve_project_file(path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    if checkpoint_path.exists():
        # Only replace a checkpoint previously created by this tool.
        load_checkpoint(checkpoint_path, {"game_id": checkpoint["game_id"]}, required=True)
    temp_path = checkpoint_path.with_name(checkpoint_path.name + ".tmp")
    temp_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(checkpoint_path)


def checkpoint_resume_page(checkpoint: dict[str, Any], *, apply: bool) -> int:
    if apply and checkpoint.get("pending_apply"):
        return int(checkpoint.get("apply_next_page", checkpoint["next_page"]))
    return int(checkpoint["next_page"])


def plan_preview_updates(connection: Any, records: list[dict[str, Any]],
                         limit: int = 50,
                         game: dict[str, Any] | None = None) -> dict[str, Any]:
    """Match only by the GameBanana composite identity and plan preview-only updates."""
    target_game = game or LEGACY_GAME
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    result: dict[str, Any] = {
        "fetched": len(records), "matched": 0, "valid_image_urls": 0,
        "updates": [], "unchanged": 0, "skipped": 0,
        "no_image_or_invalid": 0, "already_highres": 0,
        "duplicate_records": 0, "skip_reasons": {}, "sample_ids": [],
    }

    def skip(reason: str, *, invalid_image: bool = False) -> None:
        result["skipped"] += 1
        result["skip_reasons"][reason] = result["skip_reasons"].get(reason, 0) + 1
        if invalid_image:
            result["no_image_or_invalid"] += 1

    seen: set[tuple[str, str, int]] = set()
    for record in records:
        item_id = record.get("item_id") if isinstance(record, dict) else None
        source = record.get("source") if isinstance(record, dict) else None
        item_type = record.get("item_type") if isinstance(record, dict) else None
        if source != SOURCE or item_type != ITEM_TYPE or not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            skip("invalid_identity", invalid_image=True)
            continue
        if record.get("game_id") != target_game["game_id"]:
            skip("wrong_game", invalid_image=True)
            continue
        identity = (source, item_type, item_id)
        if identity in seen:
            result["duplicate_records"] += 1
            continue
        seen.add(identity)
        if result["matched"] >= limit:
            skip("limit_reached")
            continue
        row = connection.execute(
            "SELECT game_id, preview_urls_json FROM mods "
            "WHERE source=? AND item_type=? AND item_id=?",
            identity,
        ).fetchone()
        if row is None or row["game_id"] != target_game["game_id"]:
            skip("not_in_local_database")
            continue
        result["matched"] += 1
        result["sample_ids"].append(item_id)
        if _has_original_metadata(row["preview_urls_json"]):
            result["already_highres"] += 1
            skip("already_has_original")
            continue
        existing = _stored_images(row["preview_urls_json"])
        incoming_source = record.get("preview_images")
        rich = isinstance(incoming_source, list)
        if rich:
            verified_source = [image for image in incoming_source
                               if isinstance(image, dict) and image.get("original_verified") is True]
            unverified_count = len(incoming_source) - len(verified_source)
            for _ in range(unverified_count):
                skip("source_original_not_verified", invalid_image=True)
            incoming = _stored_images(json.dumps(verified_source, ensure_ascii=False))
        else:
            incoming = _stored_images(json.dumps(record.get("preview_urls", []), ensure_ascii=False))
        result["valid_image_urls"] += len(incoming)
        by_url = {_asset_key(image["image_url"]): image for image in existing}
        for image in incoming:
            by_url[_asset_key(image["image_url"])] = image
        merged = list(by_url.values())
        rich = rich or _is_rich_storage(row["preview_urls_json"])
        if not incoming:
            skip("no_verified_original", invalid_image=True)
            continue
        if merged == existing:
            result["unchanged"] += 1
            continue
        result["updates"].append({"identity": identity, "preview_images": merged, "rich": rich})
    result["records_to_update"] = len(result["updates"])
    return result


def apply_preview_updates(connection: Any, updates: list[dict[str, Any]], *,
                          backup: Callable[[], None],
                          game: dict[str, Any] | None = None) -> int:
    """Backup once, then atomically update only preview_urls_json."""
    if not updates:
        return 0
    target_game = game or LEGACY_GAME
    backup()
    changed = 0
    connection.execute("BEGIN IMMEDIATE")
    try:
        for update in updates:
            source, item_type, item_id = update["identity"]
            row = connection.execute(
                "SELECT preview_urls_json FROM mods WHERE source=? AND item_type=? AND item_id=? AND game_id=?",
                (source, item_type, item_id, target_game["game_id"]),
            ).fetchone()
            if row is None:
                continue
            if _has_original_metadata(row["preview_urls_json"]):
                continue
            existing = _stored_images(row["preview_urls_json"])
            by_url = {_asset_key(image["image_url"]): image for image in existing}
            for image in update["preview_images"]:
                by_url[_asset_key(image["image_url"])] = image
            merged = list(by_url.values())
            if merged == existing:
                continue
            stored = (merged if update.get("rich") or _is_rich_storage(row["preview_urls_json"])
                      else [image["image_url"] for image in merged])
            connection.execute(
                "UPDATE mods SET preview_urls_json=? WHERE source=? AND item_type=? AND item_id=? AND game_id=?",
                (json.dumps(stored, ensure_ascii=False, separators=(",", ":")),
                 source, item_type, item_id, target_game["game_id"]),
            )
            changed += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return changed


def run_backfill(connection: Any, records: list[dict[str, Any]], *, limit: int = 50,
                 dry_run: bool = True,
                 before_write: Callable[[], None] | None = None,
                 game: dict[str, Any] | None = None) -> dict[str, Any]:
    target_game = game or LEGACY_GAME
    plan = plan_preview_updates(connection, records, limit, target_game)
    database_total = connection.execute("SELECT COUNT(*) FROM mods").fetchone()[0]
    if dry_run:
        updated = 0
    else:
        if plan["updates"] and before_write is None:
            raise RuntimeError("A successful database backup is required before writing.")
        updated = apply_preview_updates(connection, plan["updates"],
                                        backup=before_write or (lambda: None), game=target_game)
    plan["updated"] = updated
    plan["database_total"] = database_total
    plan["status"] = "dry_run" if dry_run else "success"
    return plan


def _report_path(game_id: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return ROOT / "logs" / "preview_backfill" / f"game_{game_id}_run_{stamp}.json"


def _write_json_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill verified GameBanana original preview URLs for existing MODs.")
    parser.add_argument("--game", type=int, required=True, choices=tuple(GAMES_BY_ID),
                        help="Game ID from config/games.json.")
    parser.add_argument("--item-id", type=int,
                        help="Process exactly one MOD ID through its ID-addressed profile endpoint.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=50)
    continuation = parser.add_mutually_exclusive_group()
    continuation.add_argument("--start-page", type=int,
                              help="Start at this one-based source page.")
    continuation.add_argument("--resume", action="store_true",
                              help="Continue at next_page from the game's saved checkpoint.")
    parser.add_argument("--checkpoint", type=str,
                        help="Checkpoint JSON path, relative to project root or an absolute path inside it.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="Preview changes (default).")
    action.add_argument("--apply", action="store_true", help="Write preview URL changes after backup.")
    args = parser.parse_args(argv)
    limit = args.limit if args.limit is not None else (1 if args.item_id else 50)
    if not 1 <= limit <= 50:
        parser.error("--limit must be between 1 and 50")
    if args.item_id is not None and limit != 1:
        parser.error("--item-id mode requires --limit 1")
    if args.max_pages < 1 or args.max_pages > MAX_PAGES_PER_RUN:
        parser.error(f"--max-pages must be between 1 and {MAX_PAGES_PER_RUN}")
    if not 1 <= args.per_page <= MAX_PER_PAGE:
        parser.error(f"--per-page must be between 1 and {MAX_PER_PAGE}")
    if args.start_page is not None and args.start_page < 1:
        parser.error("--start-page must be at least 1")
    if args.item_id is not None and (args.start_page is not None or args.resume):
        parser.error("--item-id cannot be combined with --start-page or --resume")
    if args.item_id is not None and args.checkpoint:
        parser.error("--item-id mode does not use a pagination checkpoint")
    database_path = ROOT / "data" / "eryoutoolbox.db"
    if not database_path.is_file():
        parser.error(f"Database does not exist: {database_path}")

    selected_game = GAMES_BY_ID[args.game]
    default_checkpoint = ROOT / "logs" / "preview_backfill" / f"game_{args.game}_checkpoint.json"
    try:
        checkpoint_path = resolve_project_file(args.checkpoint or default_checkpoint)
        previous_checkpoint = (None if args.item_id is not None else
                               load_checkpoint(checkpoint_path, selected_game, required=args.resume))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if (previous_checkpoint and previous_checkpoint.get("pending_apply")
            and args.apply and not args.resume):
        parser.error("Checkpoint contains legacy uncommitted dry-run progress; use --resume --apply to honor it.")
    if (args.resume and previous_checkpoint and previous_checkpoint.get("exhausted")
            and not (args.apply and previous_checkpoint.get("pending_apply"))):
        parser.error("Checkpoint is marked exhausted; use --start-page to begin a new bounded scan.")
    start_page = (checkpoint_resume_page(previous_checkpoint, apply=args.apply)
                  if args.resume and previous_checkpoint else (args.start_page or 1))

    backup_path: Path | None = None
    report_file = _report_path(args.game)
    result: dict[str, Any] = {
        "game": selected_game, "mode": "apply" if args.apply else "dry-run",
        "start_page": None if args.item_id else start_page,
        "pages_scanned": 0, "requests": 0, "fetched": 0,
        "unique_records": 0, "matched": 0, "already_highres": 0,
        "records_to_update": 0, "valid_image_urls": 0,
        "source_records_with_originals": 0, "source_verified_original_urls": 0,
        "unchanged": 0, "skipped": 0, "skip_reasons": {},
        "failed_pages": [], "failure_reasons": [], "next_page": start_page,
        "exhausted": False, "checkpoint": str(checkpoint_path),
        "checkpoint_updated": False, "backup": None, "sample_ids": [],
        "database_total": None, "status": "failed",
    }
    connection: sqlite3.Connection | None = None
    try:
        connection = open_existing_database(database_path, read_only=not args.apply)
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            if args.item_id is not None:
                collection = fetch_exact_item(client, args.item_id, selected_game)
            else:
                collection = collect_preview_pages(
                    client, selected_game, start_page=start_page,
                    max_pages=args.max_pages, per_page=args.per_page,
                )

        def create_backup() -> None:
            nonlocal backup_path
            backup_dir = ROOT / "data" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            backup_path = backup_dir / f"eryoutoolbox_previews_{stamp}.db"
            if backup_path.exists():
                raise FileExistsError(f"Refusing to overwrite backup: {backup_path}")
            backup_database(database_path, backup_path)

        plan = plan_preview_updates(connection, collection["records"], limit=limit, game=selected_game)
        failures = collection["failure_reasons"]
        result.update({
            "pages_scanned": collection.get("pages_scanned", 0),
            "requests": collection["request_count"],
            "fetched": collection.get("raw_record_count", len(collection["records"])),
            "unique_records": len(collection["records"]),
            "matched": plan["matched"], "already_highres": plan["already_highres"],
            "records_to_update": plan["records_to_update"],
            "valid_image_urls": plan["valid_image_urls"],
            "source_records_with_originals": sum(
                any(isinstance(image, dict) and image.get("original_verified") is True
                    for image in record.get("preview_images", []))
                for record in collection["records"]
            ),
            "source_verified_original_urls": sum(
                1 for record in collection["records"]
                for image in record.get("preview_images", [])
                if isinstance(image, dict) and image.get("original_verified") is True
                and valid_image_url(image.get("image_url"))
            ),
            "unchanged": plan["unchanged"], "skipped": plan["skipped"],
            "skip_reasons": plan["skip_reasons"],
            "failed_pages": collection["failed_pages"], "failure_reasons": failures,
            "next_page": collection.get("next_page"),
            "exhausted": collection.get("exhausted", False),
            "page_results": collection.get("page_results", []),
            "sample_ids": plan["sample_ids"][:5],
            "database_total": connection.execute("SELECT COUNT(*) FROM mods").fetchone()[0],
        })
        if args.item_id is not None:
            result["target_item_id"] = args.item_id
            result["image_count"] = collection.get("image_count")
            result["verified_original_count"] = collection.get("verified_original_count")
        if args.apply and plan["updates"]:
            result["updated"] = apply_preview_updates(
                connection, plan["updates"], backup=create_backup, game=selected_game,
            )
            result["backup"] = str(backup_path) if backup_path else None
            result["database_total"] = connection.execute("SELECT COUNT(*) FROM mods").fetchone()[0]
        else:
            result["updated"] = 0

        if failures:
            result["status"] = "partial" if collection["records"] else "failed"
        elif args.item_id is not None or collection.get("exhausted"):
            result["status"] = "success"
        else:
            result["status"] = "incomplete"

        # Dry-runs are reports only: never advance the committed scan position.
        # Legacy checkpoints with pending_apply are retained as-is until an
        # explicit --resume --apply consumes that previously recorded position.
        if args.item_id is None and args.apply:
            old = previous_checkpoint if args.resume and previous_checkpoint else {}
            cumulative_failed = list(old.get("failed_pages", []))
            cumulative_failed.extend(collection["failed_pages"])
            checkpoint = {
                "format": CHECKPOINT_FORMAT,
                "game_id": selected_game["game_id"], "game_name": selected_game["name"],
                "next_page": collection["next_page"], "exhausted": collection["exhausted"],
                # Keep the legacy keys for older readers, but only mark a
                # position committed after the database operation succeeded.
                "apply_next_page": collection["next_page"], "pending_apply": False,
                "scanned_pages_total": int(old.get("scanned_pages_total", 0)) + collection["pages_scanned"],
                "requests_total": int(old.get("requests_total", 0)) + collection["request_count"],
                "records_total": int(old.get("records_total", 0)) + collection["raw_record_count"],
                "failed_pages": list(dict.fromkeys(cumulative_failed)),
                "updated_total": int(old.get("updated_total", 0)) + result["updated"],
                "matched_total": int(old.get("matched_total", 0)) + result["matched"],
                "skipped_total": int(old.get("skipped_total", 0)) + result["skipped"],
                "last_run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "last_failure_reasons": failures,
                "last_page_results": collection.get("page_results", []),
                "last_run_summary": {key: result[key] for key in (
                    "pages_scanned", "requests", "fetched", "unique_records", "matched",
                    "already_highres", "records_to_update", "valid_image_urls",
                    "updated", "skipped", "status")},
            }
            save_checkpoint(checkpoint_path, checkpoint)
            result["checkpoint_updated"] = True
    except Exception as exc:
        result["status"] = "failed"
        result["failure_reasons"].append({"reason": f"{type(exc).__name__}: {exc}"})
    finally:
        if connection is not None:
            connection.close()

    result["backup"] = result.get("backup") or None
    try:
        _write_json_new(report_file, result)
        result["report_file"] = str(report_file)
    except Exception as exc:
        result["failure_reasons"].append({"reason": f"Could not save run report: {exc}"})
        result["status"] = "failed"

    print(f"游戏：{selected_game['name']}（{selected_game['game_id']}）")
    if args.item_id is not None:
        print(f"精确 MOD ID：{args.item_id}；源图片数：{result.get('image_count', 0)}；有效原图数：{result.get('verified_original_count', 0)}")
    print(f"扫描页数：{result['pages_scanned']}；请求数：{result['requests']}；起始页：{result['start_page'] or '精确 ID'}")
    print(f"获取记录：{result['fetched']}；去重记录：{result['unique_records']}；匹配本地 MOD：{result['matched']}")
    print(f"已有高清图：{result['already_highres']}；待回填：{result['records_to_update']}；成功解析原图 URL：{result['source_verified_original_urls']}")
    print(f"跳过：{result['skipped']}；原因：{result['skip_reasons']}")
    print(f"失败页：{result['failed_pages']}；失败原因：{result['failure_reasons']}")
    print(f"下一次续扫页：{result['next_page']}；扫描结束标记：{result['exhausted']}")
    print(f"数据库作品总数：{result['database_total']}；更新：{result.get('updated', 0)}；备份：{result['backup'] or '无'}")
    print(f"检查点：{result['checkpoint']}（本次已更新：{result['checkpoint_updated']}）")
    print(f"状态：{result['status']}；报告：{result.get('report_file', report_file)}")
    if args.item_id is None:
        continuation = "--resume" if result["checkpoint_updated"] else f"--start-page {result['next_page']}"
        print(f"续扫参数：--game {args.game} {continuation} --max-pages {args.max_pages} --per-page {args.per_page} --limit {limit}")
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
