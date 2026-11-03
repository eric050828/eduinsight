"""SQLite connection policy and serialized, process-local lazy initialization."""

from __future__ import annotations

import sqlite3
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

from .config import settings

_lock = threading.RLock()
_initialized: OrderedDict[tuple, None] = OrderedDict()


def connect(path: str, *, uri: bool = False, readonly: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=settings.sqlite_busy_timeout_ms / 1000, uri=uri)
    try:
        conn.execute(f"PRAGMA busy_timeout = {settings.sqlite_busy_timeout_ms}")
        if not readonly:
            # WAL persists on disk. Repeating the read of the mode avoids a write
            # lock on every request and permits readers during a writer transaction.
            if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                conn.execute("PRAGMA journal_mode = WAL")
        return conn
    except BaseException:
        conn.close()
        raise


@contextmanager
def schema_once(conn: sqlite3.Connection, name: str):
    """Yield whether initialization is needed; cache only after a successful commit.

    File identity handles isolated test DBs and replacement at the same path.
    In-memory connections cannot share schemas and are deliberately not cached.
    The bounded cache supports long-running processes switching database paths.
    Call before starting a request's write transaction.
    """
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    identity = None
    if path:
        resolved = Path(path).resolve()
        stat = resolved.stat()
        identity = (str(resolved), stat.st_dev, stat.st_ino, name)
    with _lock:
        if identity is not None and identity in _initialized:
            _initialized.move_to_end(identity)
            yield False
            return
        try:
            yield True
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        if identity is not None:
            _initialized[identity] = None
            if len(_initialized) > 512:
                _initialized.popitem(last=False)


def is_locked(exc: BaseException) -> bool:
    code = getattr(exc, "sqlite_errorcode", 0) or 0
    return isinstance(exc, sqlite3.OperationalError) and (
        code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        or "database is locked" in str(exc).lower()
        or "database table is locked" in str(exc).lower()
        or "database schema is locked" in str(exc).lower()
    )
