from __future__ import annotations

import argparse
from typing import Optional

from .database import Database
from . import orm_models  # noqa: F401  # Register all mapped tables before create_all.


def init_database(database_url: Optional[str] = None) -> Database:
    database = Database(database_url)
    database.create_schema()
    return database


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Create the current demo database schema.")
    parser.add_argument("--database-url", help="SQLAlchemy URL; defaults to NL_JSON_DATABASE_URL.")
    args = parser.parse_args(argv)

    database = init_database(args.database_url)
    print(f"Initialized database at {database.url}")
    database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
