"""Read-only, parameterized SQLite queries for the local MOD browser."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import unquote, urlsplit

from .content_ratings import source_ratings, rating_matches

SORT_COLUMNS = {
    "first_seen": "m.first_seen_at",
    "created": "m.created_at",
    "updated": "m.updated_at",
}


class DatabaseReadError(RuntimeError):
    """Raised when the browser cannot safely read its configured database."""


def readonly_connection(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path).resolve()
    if not path.is_file():
        raise DatabaseReadError(f"Database does not exist: {path}")
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection
    except sqlite3.Error as exc:
        raise DatabaseReadError(f"Could not open database read-only: {exc}") from exc


def valid_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        parsed.port
        hostname = parsed.hostname.encode("idna").decode("ascii")
        return bool(hostname and not any(char.isspace() for char in hostname))
    except ValueError:
        return False
    except UnicodeError:
        return False


_GB_IMAGE_VARIANT = re.compile(r"^\d+-\d+_(.+)$")


def _gallery_asset_key(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    parent, _, filename = path.rpartition("/")
    variant = _GB_IMAGE_VARIANT.fullmatch(filename)
    if variant:
        filename = variant.group(1)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parent}", filename


def parse_preview_images(raw_value: Any) -> tuple[list[dict[str, str]], bool]:
    """Read new image objects and legacy string arrays without losing source order."""
    if not isinstance(raw_value, str) or not raw_value:
        return [], False
    try:
        value = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return [], True
    if not isinstance(value, list):
        return [], True
    images: list[dict[str, str]] = []
    invalid_seen = False
    seen_assets: set[tuple[str, str]] = set()
    for item in value:
        if isinstance(item, str):
            candidates = {"image_url": item, "thumbnail_url": item, "switch_url": item}
        elif isinstance(item, dict):
            candidates = {
                "image_url": item.get("image_url"),
                "thumbnail_url": item.get("thumbnail_url"),
                "switch_url": item.get("switch_url"),
            }
            if not valid_http_url(candidates["image_url"]):
                candidates["image_url"] = (candidates["thumbnail_url"]
                                           if valid_http_url(candidates["thumbnail_url"])
                                           else candidates["switch_url"])
        else:
            invalid_seen = True
            continue
        image_url = candidates["image_url"]
        if not valid_http_url(image_url):
            invalid_seen = True
            continue
        thumbnail = candidates["thumbnail_url"]
        switch = candidates["switch_url"]
        image = {
            "image_url": image_url,
            "thumbnail_url": thumbnail if valid_http_url(thumbnail) else image_url,
            "switch_url": switch if valid_http_url(switch) else (
                thumbnail if valid_http_url(thumbnail) else image_url),
        }
        key = _gallery_asset_key(image_url)
        if key not in seen_assets:
            seen_assets.add(key)
            images.append(image)
    return images, invalid_seen and not images


def parse_gallery_urls(raw_value: Any) -> tuple[list[str], bool]:
    """Compatibility helper returning high-resolution URLs in source order."""
    images, invalid = parse_preview_images(raw_value)
    return [image["image_url"] for image in images], invalid


def parse_preview_data(raw_value: Any) -> tuple[list[str], bool]:
    images, invalid = parse_preview_images(raw_value)
    return list(dict.fromkeys(image["thumbnail_url"] for image in images)), invalid


def parse_preview_urls(raw_value: Any) -> list[str]:
    """Return only safe-to-render HTTP(S) preview URLs."""
    return parse_preview_data(raw_value)[0]


def preview_display_decision(record: dict[str, Any], show_unrated: bool = False) -> tuple[str, list[str]]:
    urls = record.get("preview_urls", [])
    urls = [url for url in urls if valid_http_url(url)] if isinstance(urls, list) else []
    if not urls:
        return ("INVALID_URL", []) if record.get("preview_invalid") else ("NO_IMAGE", [])
    rating = record.get("content_rating_status")
    if rating == "ADULT":
        return "NSFW_HIDDEN", []
    if rating == "UNKNOWN" and not show_unrated:
        return "UNKNOWN_HIDDEN", []
    if rating == "SAFE" or (rating == "UNKNOWN" and show_unrated):
        return "DISPLAY", urls
    return "RATING_HIDDEN", []


def preview_urls_for_display(record: dict[str, Any], show_unrated: bool = False) -> list[str]:
    """Compatibility wrapper returning URLs only when policy allows display."""
    state, urls = preview_display_decision(record, show_unrated=show_unrated)
    return urls if state == "DISPLAY" else []


def query_mods(database_path: str | Path, *, game_id: int | None = None,
               search: str = "", sort: str = "first_seen",
               limit: int = 24, offset: int = 0,
               require_preview: bool = False, rating_codes: list[str] | None = None,
               require_updated: bool = False, subscriptions_only: bool = False,
               read_filter: str = 'all') -> dict[str, Any]:
    if sort not in SORT_COLUMNS:
        raise ValueError("Unsupported MOD sort option.")
    if limit < 1 or offset < 0:
        raise ValueError("limit must be positive and offset must not be negative.")
    if read_filter not in ('all','read','unread'):raise ValueError('Invalid read-state filter')
    where: list[str] = []
    if read_filter!='all':
        condition="EXISTS (SELECT 1 FROM user_states rs WHERE rs.source=m.source AND rs.item_type=m.item_type AND rs.item_id=m.item_id AND rs.is_read=1)"
        where.append(condition if read_filter=='read' else 'NOT '+condition)
    parameters: list[Any] = []
    if game_id is not None:
        where.append("m.game_id = ?")
        parameters.append(game_id)
    search = search.strip()
    if search:
        search_clause = "(LOWER(COALESCE(m.title, '')) LIKE LOWER(?) OR LOWER(COALESCE(m.author_name, '')) LIKE LOWER(?)"
        like = f"%{search}%"
        parameters.extend((like, like))
        if search.isdecimal() and len(search) <= 19 and int(search) <= 9223372036854775807:
            search_clause += " OR m.item_id = ?"
            parameters.append(int(search))
        where.append(search_clause + ")")
    if require_preview:
        where.append("m.preview_urls_json IS NOT NULL AND trim(m.preview_urls_json) NOT IN ('', '[]')")
    if require_updated:
        where.append('julianday(m.updated_at) IS NOT NULL')
    if rating_codes is not None:
        where.append("rating_matches(m.raw_metadata_json, ?) = 1")
        parameters.append(json.dumps(rating_codes))
    clause = " WHERE " + " AND ".join(where) if where else ""
    selected = (
        "m.source, m.item_type, m.item_id, m.game_id, m.game_name, m.title, "
        "m.original_url, m.author_id, m.author_name, m.author_url, m.created_at, "
        "m.updated_at, m.version, m.content_rating_status, m.preview_urls_json, "
        "m.raw_metadata_json, m.first_seen_at, us.is_read, us.is_favorite, us.is_ignored, us.workflow_status, "
        "(SELECT MAX(e.detected_at) FROM mod_events e WHERE e.source=m.source AND e.item_type=m.item_type "
        "AND e.item_id=m.item_id AND e.event_type='source_updated') AS source_update_detected_at"
    )
    order = SORT_COLUMNS[sort]
    connection = readonly_connection(database_path)
    try:
        if subscriptions_only:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='author_subscriptions' AND type='table'").fetchone():
                clause += (' AND ' if clause else ' WHERE ') + 'EXISTS (SELECT 1 FROM author_subscriptions a WHERE a.source=m.source AND a.author_id=m.author_id)'
                selected += ', (SELECT a.followed_at FROM author_subscriptions a WHERE a.source=m.source AND a.author_id=m.author_id) AS subscription_followed_at'
                selected += ", (SELECT json_extract(s.error_summary,'$.author_check.baseline_at') FROM sync_runs s WHERE s.source=m.source AND json_valid(s.error_summary) AND json_extract(s.error_summary,'$.author_check.author_id')=m.author_id ORDER BY s.run_id DESC LIMIT 1) AS author_baseline_at"
                selected += ", (SELECT MIN(e.detected_at) FROM mod_events e WHERE e.source=m.source AND e.item_type=m.item_type AND e.item_id=m.item_id AND e.event_type='first_seen') AS local_first_seen_event_at"
                if require_updated:
                    clause += " AND EXISTS (SELECT 1 FROM mod_events e WHERE e.source=m.source AND e.item_type=m.item_type AND e.item_id=m.item_id AND e.event_type='source_updated')"
            else:
                clause += (' AND ' if clause else ' WHERE ') + '0'
        connection.create_function("rating_matches", 2, rating_matches)
        total = connection.execute("SELECT COUNT(*) FROM mods m" + clause, parameters).fetchone()[0]
        rows = connection.execute(
            f"SELECT {selected} FROM mods m "
            "LEFT JOIN user_states us ON us.source=m.source AND us.item_type=m.item_type AND us.item_id=m.item_id"
            f"{clause} ORDER BY julianday({order}) DESC, m.item_id DESC, m.source, m.item_type LIMIT ? OFFSET ?",
            (*parameters, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["source_ratings"] = source_ratings(item.pop("raw_metadata_json", None))
            item["preview_urls"], item["preview_invalid"] = parse_preview_data(
                item.pop("preview_urls_json", None))
            if require_preview and not item["preview_urls"]:
                continue
            item["content_rating_status"] = item.get("content_rating_status") or "UNKNOWN"
            items.append(item)
        return {"total_count": total, "items": items}
    except sqlite3.Error as exc:
        raise DatabaseReadError(f"Database query failed: {exc}") from exc
    finally:
        connection.close()


def query_discovery_status(database_path: str | Path, game_id: int | None = None) -> dict[str, Any]:
    """Scope is the selected game, or any game for the all-games view."""
    connection = readonly_connection(database_path)
    try:
        clause = ' WHERE game_id=?' if game_id is not None else ''
        params = (game_id,) if game_id is not None else ()
        count = connection.execute('SELECT COUNT(*) FROM mods' + clause, params).fetchone()[0]
        row = connection.execute(
            "SELECT source,game_id,started_at,ended_at,status FROM sync_runs WHERE source='gamebanana'" +
            (' AND game_id=?' if game_id is not None else '') +
            ' ORDER BY julianday(started_at) DESC,run_id DESC LIMIT 1', params).fetchone()
        return {'local_count': count, 'game_id': game_id, 'coverage': 'unverified',
                'last_sync': dict(row) if row else None}
    except sqlite3.Error as exc:
        raise DatabaseReadError(f'Discovery status query failed: {exc}') from exc
    finally:
        connection.close()


def query_mod_detail(database_path: str | Path, *, source: str,
                     item_type: str, item_id: int) -> dict[str, Any] | None:
    """Read one MOD detail by its composite key without changing the database."""
    if not source or not item_type or not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
        raise ValueError("A valid MOD identity is required.")
    selected = (
        "m.source, m.item_type, m.item_id, m.game_id, m.game_name, m.title, "
        "m.original_url, m.author_id, m.author_name, m.author_url, m.created_at, "
        "m.updated_at, m.version, m.category, m.subcategory, m.tags_json, "
        "m.content_rating_status, m.preview_urls_json, m.raw_metadata_json"
    )
    connection = readonly_connection(database_path)
    try:
        row = connection.execute(
            f"SELECT {selected} FROM mods m WHERE m.source=? AND m.item_type=? AND m.item_id=?",
            (source, item_type, item_id),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["source_ratings"] = source_ratings(result.get("raw_metadata_json"))
        result["preview_images"], result["preview_invalid"] = parse_preview_images(
            result.pop("preview_urls_json", None))
        result["preview_urls"] = [image["image_url"] for image in result["preview_images"]]
        try:
            tags = json.loads(result.pop("tags_json", None) or "[]")
        except (TypeError, json.JSONDecodeError):
            tags = []
        result["tags"] = [tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else []
        result["content_rating_status"] = result.get("content_rating_status") or "UNKNOWN"
        try:
            metadata = json.loads(result.pop("raw_metadata_json", None) or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        source_record = metadata.get("_record") if isinstance(metadata, dict) else None
        description = source_record.get("description") if isinstance(source_record, dict) else None
        result["description"] = description if isinstance(description, str) and description.strip() else None
        return result
    except sqlite3.Error as exc:
        raise DatabaseReadError(f"Database detail query failed: {exc}") from exc
    finally:
        connection.close()


def gallery_step_index(index: int, image_count: int, step: int) -> int:
    """Move one gallery step while keeping the index inside its valid bounds."""
    if image_count <= 0:
        return 0
    return min(max(index + step, 0), image_count - 1)


def distribute_items_to_columns(items: list[dict[str, Any]], column_count: int) -> list[list[dict[str, Any]]]:
    """Place sorted items into stable vertical columns without loss or duplication."""
    if column_count < 1:
        raise ValueError("column_count must be positive.")
    columns: list[list[dict[str, Any]]] = [[] for _ in range(column_count)]
    for index, item in enumerate(items):
        columns[index % column_count].append(item)
    return columns
