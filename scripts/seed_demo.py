"""Seed the EduInsight database with realistic demo data.

Creates 4 students with distinct learning patterns to showcase
the memory-augmented AI assistant and teacher dashboard.

Usage:
    uv run python scripts/seed_demo.py [--db eduinsight.db] [--reset]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure the project source is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eduinsight.demo_data import DEMO_STUDENTS  # noqa: E402
from litemem import Memory  # noqa: E402


def seed_database(db_path: str, *, reset: bool = False) -> dict[str, int]:
    """Populate the database with demo student data.

    Args:
        db_path: Path to the SQLite database file.
        reset: If True, delete existing DB before seeding.

    Returns:
        Dict mapping user_id to number of facts added.
    """
    if reset and os.path.exists(db_path):
        os.remove(db_path)
        for suffix in ("-wal", "-shm"):
            wal = db_path + suffix
            if os.path.exists(wal):
                os.remove(wal)

    mem = Memory(db_path)
    result: dict[str, int] = {}

    for user_id, facts in DEMO_STUDENTS.items():
        for fact_text, category in facts:
            mem.add(user_id, fact_text, category=category)
        # Verify actual stored count
        actual = len(mem.list(user_id))
        result[user_id] = actual

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed EduInsight demo data")
    parser.add_argument("--db", default="eduinsight.db", help="Database path (default: eduinsight.db)")
    parser.add_argument("--reset", action="store_true", help="Delete existing DB before seeding")
    args = parser.parse_args()

    print(f"Seeding demo data into {args.db} (reset={args.reset})")
    result = seed_database(args.db, reset=args.reset)

    total = sum(result.values())
    print(f"Done! Seeded {len(result)} students, {total} memories total:")
    for uid, count in result.items():
        print(f"  {uid}: {count} memories")


if __name__ == "__main__":
    main()
