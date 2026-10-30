"""Read-only GameBanana image-metadata check for MOD 732438."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eryoutoolbox.models import extract_preview_images, valid_image_url  # noqa: E402
from eryoutoolbox.ui_queries import query_mod_detail, readonly_connection  # noqa: E402

API_URL = "https://gamebanana.com/apiv11/Mod/732438/ProfilePage"
DATABASE_PATH = ROOT / "data" / "eryoutoolbox.db"


def find_preview_media(value):
    if isinstance(value, dict):
        media = value.get("_aPreviewMedia")
        if isinstance(media, dict):
            return media
        if isinstance(value.get("_aImages"), list):
            return value
        for child in value.values():
            found = find_preview_media(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_preview_media(child)
            if found is not None:
                return found
    return None


def inspect_mod() -> int:
    try:
        existing = query_mod_detail(DATABASE_PATH, source="gamebanana",
                                    item_type="Mod", item_id=732438)
    except Exception as exc:
        print(f"Read-only database check failed: {type(exc).__name__}: {exc}")
        return 1
    if existing is None:
        print("MOD 732438 is not present in the local database; no update is planned.")
        return 1

    try:
        response = httpx.get(
            API_URL,
            timeout=httpx.Timeout(15.0, connect=8.0),
            headers={"User-Agent": "ErYouToolbox/0.2 read-only preview metadata check"},
        )
        print(f"HTTP status: {response.status_code}")
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"API check failed: {type(exc).__name__}: {exc}")
        return 1

    media = find_preview_media(payload)
    if media is None:
        keys = list(payload)[:20] if isinstance(payload, dict) else type(payload).__name__
        print(f"Preview metadata: not found; response keys/type: {keys}")
        return 1

    entries = media.get("_aImages")
    entries = entries if isinstance(entries, list) else []
    normalized = [extract_preview_images({
        "_sBaseUrl": media.get("_sBaseUrl"),
        "_aImages": [entry],
    }) for entry in entries if isinstance(entry, dict)]
    normalized = [images[0] for images in normalized if images]

    verified_images = [image for image in normalized
                       if image.get("original_verified") is True
                       and valid_image_url(image.get("image_url"))]
    originals = [image["image_url"] for image in verified_images]

    try:
        connection = readonly_connection(DATABASE_PATH)
        try:
            raw_preview = connection.execute(
                "SELECT preview_urls_json FROM mods "
                "WHERE source=? AND item_type=? AND item_id=?",
                ("gamebanana", "Mod", 732438),
            ).fetchone()
        finally:
            connection.close()
        stored = json.loads(raw_preview[0]) if raw_preview and raw_preview[0] else []
        old_format = ("rich object array" if isinstance(stored, list) and any(isinstance(x, dict) for x in stored)
                      else "legacy string array" if isinstance(stored, list) and all(isinstance(x, str) for x in stored)
                      else "unknown or empty")
    except Exception as exc:
        old_format = f"read failed: {type(exc).__name__}"

    print("MOD ID: 732438")
    print(f"Image entries: {len(entries)}")
    print(f"Entries with _sFile original: {len(originals)}")
    print(f"Valid original URLs: {len(originals)}")
    print(f"Valid normalized thumbnails: {sum(valid_image_url(item['thumbnail_url']) for item in normalized)}")
    print(f"Images missing valid _sFile original: {max(0, len(entries) - len(originals))}")
    print(f"All six originals valid: {len(entries) == 6 and len(originals) == 6}")
    print(f"Existing database format: {old_format}")
    print("New candidate format: rich image objects (image_url, thumbnail_url, switch_url)")
    old_images = existing.get("preview_images", [])
    old_originals = {image["image_url"] for image in old_images}
    new_originals = set(originals)
    print(f"Existing saved image count: {len(old_images)}")
    print(f"Dry-run would update previews: {bool(new_originals and new_originals != old_originals)}")
    if originals:
        print(f"Sample original URL: {originals[0]}")
    print("Dry-run only; database writes: none; image files downloaded: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(inspect_mod())
