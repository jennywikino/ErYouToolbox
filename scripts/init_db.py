from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from eryoutoolbox.database import initialize_database  # noqa: E402


def main() -> int:
    database_path = ROOT / "data" / "eryoutoolbox.db"
    existed = database_path.exists()
    initialize_database(database_path)
    action = "Existing database initialized safely" if existed else "Database initialized"
    print(f"{action}: {database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
