from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.database import backup_database, connect_database  # noqa: E402
from eryoutoolbox.importer import SAMPLE_NAME, import_samples, load_sample  # noqa: E402


def discover_files(samples_dir: Path, explicit_file: Path | None) -> tuple[list[Path], list[str]]:
    if explicit_file is not None:
        path = explicit_file.resolve()
        if not path.is_file():
            return [], [f"File does not exist: {path}"]
        if not SAMPLE_NAME.fullmatch(path.name):
            return [], [f"Ignored non-collector filename: {path.name}"]
        return [path], []
    if not samples_dir.is_dir():
        return [], [f"Samples directory does not exist: {samples_dir}"]
    candidates = sorted(path for path in samples_dir.glob("*.json") if SAMPLE_NAME.fullmatch(path.name))
    ignored = [f"Ignored non-collector JSON: {path.name}" for path in sorted(samples_dir.glob("*.json"))
               if not SAMPLE_NAME.fullmatch(path.name)]
    return candidates, ignored


def main() -> int:
    parser = argparse.ArgumentParser(description="Import normalized GameBanana collector samples into SQLite.")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--samples-dir", type=Path, help="Directory of recognized collector samples")
    source_group.add_argument("--file", type=Path, help="One recognized collector sample file")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="Preview without writing (default)")
    mode_group.add_argument("--apply", action="store_true", help="Back up then apply changes")
    args = parser.parse_args()
    dry_run = not args.apply
    samples_dir = args.samples_dir or (ROOT / "data" / "samples")
    database_path = ROOT / "data" / "eryoutoolbox.db"
    if not database_path.is_file():
        parser.error(f"Database does not exist; initialize it first: {database_path}")

    files, discovery_errors = discover_files(samples_dir, args.file)
    snapshots = []
    file_errors = []
    for error in discovery_errors:
        file_errors.append({"file": None, "error": error})
    for path in files:
        try:
            file_info, records = load_sample(path)
            snapshots.append((file_info, records))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            file_errors.append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})

    connection = connect_database(database_path)
    backup_path: Path | None = None
    try:
        def create_backup() -> None:
            nonlocal backup_path
            backup_dir = ROOT / "data" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = backup_dir / f"eryoutoolbox_{timestamp}.db"
            if backup_path.exists():
                raise FileExistsError(f"Refusing to overwrite existing backup: {backup_path}")
            backup_database(database_path, backup_path)

        result = import_samples(
            connection,
            snapshots,
            dry_run=dry_run,
            before_write=create_backup if args.apply else None,
        )
        result["errors"] += len(file_errors)
        result["file_errors"].extend(file_errors)
        result["input_files"] = len(files)
        result["database_path"] = str(database_path)
        result["backup_path"] = str(backup_path) if backup_path else None
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["errors"] else 0
    except Exception as exc:
        print(json.dumps({"mode": "apply" if args.apply else "dry-run",
                          "error": f"{type(exc).__name__}: {exc}",
                          "backup_path": str(backup_path) if backup_path else None},
                         ensure_ascii=False, indent=2))
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
