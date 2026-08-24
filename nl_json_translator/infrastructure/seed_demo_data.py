from __future__ import annotations

import argparse
from typing import Optional

from .init_db import init_database


def seed_demo_data(database_url: Optional[str] = None) -> int:
    """Initialize the database and return the number of inserted demo rows.

    Concrete map and location records are added by the map-data milestone. Keeping
    this entry point available now gives every later seed a single idempotent path.
    """

    database = init_database(database_url)
    database.dispose()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize and seed the demo database.")
    parser.add_argument("--database-url", help="SQLAlchemy URL; defaults to NL_JSON_DATABASE_URL.")
    args = parser.parse_args(argv)
    inserted = seed_demo_data(args.database_url)
    print(f"Demo database ready; inserted {inserted} row(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
