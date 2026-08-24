from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL_ENV = "NL_JSON_DATABASE_URL"
DEFAULT_DATABASE_PATH = Path("data") / "nl_json_translator.db"


class Base(DeclarativeBase):
    pass


def default_database_url() -> str:
    return os.environ.get(DATABASE_URL_ENV, f"sqlite:///{DEFAULT_DATABASE_PATH}")


def _prepare_sqlite_directory(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
        return
    database_path = Path(database_url.removeprefix(prefix)).expanduser()
    database_path.parent.mkdir(parents=True, exist_ok=True)


class Database:
    def __init__(self, database_url: Optional[str] = None, *, echo: bool = False):
        self.url = database_url or default_database_url()
        _prepare_sqlite_directory(self.url)
        connect_args = {"check_same_thread": False} if self.url.startswith("sqlite:") else {}
        self.engine: Engine = create_engine(self.url, echo=echo, connect_args=connect_args)
        if self.url.startswith("sqlite:"):
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_schema(self) -> None:
        Base.metadata.drop_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()


def _enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
