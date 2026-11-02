"""Read-only backup and restore verification for the project's SQLite database."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TABLES = ("mods", "user_states", "mod_events", "sync_runs")


def open_readonly(path: str | Path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.execute("PRAGMA query_only = ON")
    return connection


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_snapshot(connection: sqlite3.Connection, *, include_authors=False) -> dict[str, Any]:
    counts = {}
    for table in TABLES + (("author_subscriptions",) if include_authors else ()):
        counts[table] = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    return {"counts": counts, "user_version": version}


def integrity_result(connection: sqlite3.Connection) -> str:
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    return "; ".join(str(row[0]) for row in rows) if rows else "no result"


def foreign_key_violations(connection: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]


def verify_backup_restore(database_path: str | Path) -> dict[str, Any]:
    original = Path(database_path).resolve()
    report: dict[str, Any] = {
        "database": str(original), "passed": False, "integrity": "not checked",
        "foreign_key_violations": [], "original_unchanged": False,
        "differences": [], "error": None,
    }
    try:
        before_hash = sha256_file(original)
        source = open_readonly(original)
        try:
            original_snapshot = database_snapshot(source)
            with tempfile.TemporaryDirectory(prefix="eryoutoolbox_backup_check_") as directory:
                temp_root = Path(directory)
                backup_path = temp_root / "backup.db"
                restored_path = temp_root / "restored.db"

                backup = sqlite3.connect(backup_path, timeout=5.0)
                try:
                    source.backup(backup)
                finally:
                    backup.close()

                backup_source = open_readonly(backup_path)
                restored = sqlite3.connect(restored_path, timeout=5.0)
                try:
                    backup_source.backup(restored)
                    restored.commit()
                finally:
                    restored.close()
                    backup_source.close()

                recovered = open_readonly(restored_path)
                try:
                    report["integrity"] = integrity_result(recovered)
                    report["foreign_key_violations"] = foreign_key_violations(recovered)
                    restored_snapshot = database_snapshot(recovered)
                finally:
                    recovered.close()

                report["original"] = original_snapshot
                report["restored"] = restored_snapshot
                for key in ("counts", "user_version"):
                    if original_snapshot[key] != restored_snapshot[key]:
                        report["differences"].append({"field": key,
                            "original": original_snapshot[key], "restored": restored_snapshot[key]})
        finally:
            source.close()
        report["original_unchanged"] = sha256_file(original) == before_hash
        if not report["original_unchanged"]:
            report["differences"].append({"field": "original_database_sha256",
                                          "reason": "Database bytes changed during verification."})
        report["passed"] = (
            report["integrity"] == "ok"
            and not report["foreign_key_violations"]
            and not report["differences"]
            and report["original_unchanged"]
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        try:
            report["original_unchanged"] = sha256_file(original) == before_hash
        except (OSError, UnboundLocalError):
            pass
    return report


def format_count(report: dict[str, Any], table: str) -> str:
    original = report.get("original", {}).get("counts", {}).get(table, "?")
    restored = report.get("restored", {}).get("counts", {}).get(table, "?")
    return f"{original} / {restored}"


def print_report(report: dict[str, Any]) -> None:
    print(f"Backup verification: {'PASS' if report['passed'] else 'FAIL'}")
    print(f"Integrity: {report['integrity']}")
    violations = report["foreign_key_violations"]
    print(f"Foreign keys: {len(violations)} violation(s)" + (f"; {violations[:3]}" if violations else ""))
    print(f"MOD count: {format_count(report, 'mods')}")
    print(f"User states: {format_count(report, 'user_states')}")
    print(f"Events: {format_count(report, 'mod_events')}")
    print(f"Sync runs: {format_count(report, 'sync_runs')}")
    original_version = report.get("original", {}).get("user_version", "?")
    restored_version = report.get("restored", {}).get("user_version", "?")
    print(f"Schema version: {original_version} / {restored_version}")
    print(f"Original database unchanged: {'yes' if report['original_unchanged'] else 'no'}")
    if report.get("error"):
        print(f"Error: {report['error']}")
    for difference in report.get("differences", []):
        print(f"Difference: {difference}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a read-only SQLite backup and restore round trip.")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "eryoutoolbox.db")
    args = parser.parse_args()
    if not args.database.is_file():
        print(f"Backup verification: FAIL\nError: Database not found: {args.database}")
        print("Original database unchanged: yes")
        return 1
    report = verify_backup_restore(args.database)
    print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
