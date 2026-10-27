"""Normalization helpers for GameBanana Mod index records."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _nested(record: dict[str, Any], key: str, field: str) -> Any:
    value = record.get(key)
    return value.get(field) if isinstance(value, dict) else None


def _url_list(media: Any) -> list[str]:
    """Only preserve explicit URL strings from known media fields; never construct URLs."""
    urls: list[str] = []
    if isinstance(media, dict):
        for value in media.values():
            if isinstance(value, str) and value.startswith(("https://", "http://")):
                urls.append(value)
            elif isinstance(value, dict):
                for nested_value in value.values():
                    if isinstance(nested_value, str) and nested_value.startswith(("https://", "http://")):
                        urls.append(nested_value)
    elif isinstance(media, list):
        for item in media:
            if isinstance(item, dict):
                for value in item.values():
                    if isinstance(value, str) and value.startswith(("https://", "http://")):
                        urls.append(value)
    return list(dict.fromkeys(urls))


def normalize_record(record: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    game_id = _positive_int(_nested(record, "_aGame", "_idRow"))
    submitter = record.get("_aSubmitter")
    if not isinstance(submitter, dict):
        submitter = {}
    root_category = record.get("_aRootCategory")
    if not isinstance(root_category, dict):
        root_category = {}
    subcategory = record.get("_aSubCategory")
    if not isinstance(subcategory, dict):
        subcategory = {}
    tags = record.get("_aTags")
    tags = [tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else []

    def timestamp(field: str) -> str | None:
        value = _positive_int(record.get(field))
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return None

    return {
        "source": "gamebanana",
        "item_type": record.get("_sModelName") if isinstance(record.get("_sModelName"), str) else None,
        "item_id": _positive_int(record.get("_idRow")),
        "game_id": game_id,
        "game_name": game.get("name"),
        "title": record.get("_sName") if isinstance(record.get("_sName"), str) else None,
        "original_url": record.get("_sProfileUrl") if isinstance(record.get("_sProfileUrl"), str) else None,
        "author_id": _positive_int(submitter.get("_idRow")),
        "author_name": submitter.get("_sName") if isinstance(submitter.get("_sName"), str) else None,
        "author_url": submitter.get("_sProfileUrl") if isinstance(submitter.get("_sProfileUrl"), str) else None,
        "created_at": timestamp("_tsDateAdded"),
        "created_at_timestamp": _positive_int(record.get("_tsDateAdded")),
        "modified_at": timestamp("_tsDateModified"),
        "modified_at_timestamp": _positive_int(record.get("_tsDateModified")),
        "updated_at": timestamp("_tsDateUpdated"),
        "updated_at_timestamp": _positive_int(record.get("_tsDateUpdated")),
        "version": record.get("_sVersion") if isinstance(record.get("_sVersion"), str) else None,
        "category": root_category.get("_sName") if isinstance(root_category.get("_sName"), str) else None,
        "subcategory": subcategory.get("_sName") if isinstance(subcategory.get("_sName"), str) else None,
        "tags": tags,
        "preview_urls": _url_list(record.get("_aPreviewMedia")),
        "content_rating_status": "UNKNOWN",
        "has_content_ratings": record.get("_bHasContentRatings") if isinstance(record.get("_bHasContentRatings"), bool) else None,
    }
