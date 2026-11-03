"""Normalization helpers for GameBanana Mod index records."""
from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _nested(record: dict[str, Any], key: str, field: str) -> Any:
    value = record.get(key)
    return value.get(field) if isinstance(value, dict) else None


_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_LIST_IMAGE_FIELDS = ("_sFile530", "_sFile220", "_sFile100", "_sFile")
_GALLERY_THUMB_FIELDS = ("_sFile100", "_sFile220", "_sFile530", "_sFile")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".test", ".invalid", ".example")


def valid_image_url(value: Any) -> bool:
    """Accept only well-formed public HTTP(S) URLs without local hosts or traversal."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        if scheme not in {"http", "https"} or not parsed.netloc or not host:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        port = parsed.port
        if port is not None and port != (443 if scheme == "https" else 80):
            return False
        normalized_host = host.rstrip(".").encode("idna").decode("ascii").lower()
        if not normalized_host or "." not in normalized_host:
            return False
        if normalized_host.endswith(_LOCAL_SUFFIXES):
            return False
        try:
            if not ipaddress.ip_address(normalized_host).is_global:
                return False
        except ValueError:
            labels = normalized_host.split(".")
            if len(normalized_host) > 253 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
                return False
            if len(labels[-1]) < 2:
                return False
        decoded_path = unquote(parsed.path)
        if "\\" in decoded_path or "\x00" in decoded_path:
            return False
        if any(part in {".", ".."} for part in decoded_path.split("/")):
            return False
        return bool(decoded_path and decoded_path != "/")
    except (UnicodeError, ValueError):
        return False


def _safe_base_url(value: Any) -> str | None:
    if not valid_image_url(value):
        return None
    parsed = urlsplit(value)
    if parsed.query or parsed.fragment:
        return None
    return value.rstrip("/")


def _safe_filename(value: Any) -> str | None:
    if not isinstance(value, str) or not _SAFE_FILENAME.fullmatch(value):
        return None
    if value in {".", ".."} or ".." == value.strip("."):
        return None
    return value


def _image_entry_url(image: dict[str, Any], base_url: str | None,
                     fields: tuple[str, ...] = _LIST_IMAGE_FIELDS,
                     allow_direct: bool = True) -> str | None:
    """Resolve a URL from existing source fields without inventing filenames."""
    for field in fields:
        candidate = image.get(field)
        if valid_image_url(candidate):
            return candidate
        filename = _safe_filename(candidate)
        if filename and base_url:
            base = urlsplit(base_url)
            path = base.path.rstrip("/") + "/" + quote(filename, safe="._-")
            combined = urlunsplit((base.scheme, base.netloc, path, "", ""))
            if valid_image_url(combined):
                return combined
    if allow_direct:
        for field in ("_sUrl", "url"):
            direct = image.get(field)
            if valid_image_url(direct):
                return direct
    return None


def extract_preview_images(media: Any) -> list[dict[str, Any]]:
    """Extract original, card, and switch-thumbnail URLs per source image."""
    images: list[dict[str, Any]] = []

    def append_direct(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                if child_key == "_aImages":
                    entries = child if isinstance(child, list) else []
                    base_url = _safe_base_url(value.get("_sBaseUrl"))
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        image_base = _safe_base_url(entry.get("_sBaseUrl")) or base_url
                        original = _image_entry_url(entry, image_base, ("_sFile",), allow_direct=False)
                        thumbnail = _image_entry_url(entry, image_base, _LIST_IMAGE_FIELDS)
                        switch_thumbnail = _image_entry_url(entry, image_base, _GALLERY_THUMB_FIELDS)
                        if original or thumbnail:
                            high = original or thumbnail
                            images.append({
                                "image_url": high,
                                "thumbnail_url": thumbnail or high,
                                "switch_url": switch_thumbnail or thumbnail or high,
                                "original_verified": original is not None,
                            })
                elif child_key != "_sBaseUrl":
                    append_direct(child, child_key)
        elif isinstance(value, list):
            for child in value:
                append_direct(child, key)
        elif isinstance(value, str) and key != "_sBaseUrl" and valid_image_url(value):
            images.append({"image_url": value, "thumbnail_url": value, "switch_url": value,
                           "original_verified": False})

    append_direct(media)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for image in images:
        if image["image_url"] not in seen:
            seen.add(image["image_url"])
            unique.append(image)
    return unique


def extract_preview_urls(media: Any) -> list[str]:
    """Return card-sized URLs for compatibility with existing callers."""
    return list(dict.fromkeys(image["thumbnail_url"] for image in extract_preview_images(media)))


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

    preview_images = extract_preview_images(record.get("_aPreviewMedia"))

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
        "preview_urls": list(dict.fromkeys(image["thumbnail_url"] for image in preview_images)),
        "preview_images": preview_images,
        "source_rating_fields": {key: record[key] for key in ("_aContentRatings", "_bHasContentRatings", "_sInitialVisibility") if key in record},
        "content_rating_status": "UNKNOWN",
        "has_content_ratings": record.get("_bHasContentRatings") if isinstance(record.get("_bHasContentRatings"), bool) else None,
        "metrics": {label:record[key] for label,key in (('likes','_nLikeCount'),('views','_nViewCount'),('downloads','_nDownloadCount'),('comments','_nPostCount')) if type(record.get(key)) is int and record[key]>=0},
    }
