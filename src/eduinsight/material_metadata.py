"""Persistent material metadata, separate from Lite-Mem's chunk schema."""

from __future__ import annotations

import mimetypes
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import settings


def material_kind(filename: str) -> str:
    if filename.endswith(".youtube.md"):
        return "youtube"
    return Path(filename).suffix.lstrip(".").lower()


class MaterialMetadata:
    def __init__(self, db_path: str | None = None):
        # Capture the path so a background job uses the upload's database.
        self.db_path = db_path or settings.auth_db_path
        Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        with self._db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS course_material_metadata (
                    course_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    size_bytes INTEGER,
                    content_type TEXT,
                    kind TEXT NOT NULL,
                    uploaded_at TEXT,
                    uploaded_by INTEGER,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    error TEXT,
                    PRIMARY KEY (course_id, filename)
                )
            """)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def start(self, course_id: str, filename: str, size_bytes: int,
              content_type: str | None, uploaded_by: int) -> bool:
        """Reserve a filename; concurrent uploads of that filename are rejected."""
        with self._db() as conn:
            cur = conn.execute("""
                INSERT INTO course_material_metadata
                    (course_id, filename, size_bytes, content_type, kind,
                     uploaded_at, uploaded_by, chunk_count, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'indexing', NULL)
                ON CONFLICT(course_id, filename) DO UPDATE SET
                    size_bytes=excluded.size_bytes, content_type=excluded.content_type,
                    kind=excluded.kind, uploaded_at=excluded.uploaded_at,
                    uploaded_by=excluded.uploaded_by, chunk_count=0,
                    status='indexing', error=NULL
                WHERE course_material_metadata.status != 'indexing'
            """, (course_id, filename, size_bytes, content_type, material_kind(filename),
                  datetime.now(timezone.utc).isoformat(), uploaded_by))
            return cur.rowcount == 1

    def finish(self, course_id: str, filename: str, chunk_count: int,
               error: str | None = None) -> None:
        with self._db() as conn:
            conn.execute("""
                UPDATE course_material_metadata SET status=?, chunk_count=?, error=?
                WHERE course_id=? AND filename=?
            """, ("failed" if error is not None else "done", chunk_count, error,
                  course_id, filename))

    def backfill(self, course_id: str, counts: dict[str, int]) -> None:
        with self._db() as conn:
            conn.executemany("""
                INSERT OR IGNORE INTO course_material_metadata
                    (course_id, filename, content_type, kind, chunk_count, status)
                VALUES (?, ?, ?, ?, ?, 'done')
            """, [(course_id, name, mimetypes.guess_type(name)[0], material_kind(name), count)
                  for name, count in counts.items()])

    def get(self, course_id: str, filename: str) -> dict | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM course_material_metadata WHERE course_id=? AND filename=?",
                (course_id, filename),
            ).fetchone()
        return dict(row) if row else None

    def list(self, course_id: str) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM course_material_metadata WHERE course_id=? ORDER BY filename",
                (course_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, course_id: str, filename: str) -> bool:
        with self._db() as conn:
            return conn.execute(
                "DELETE FROM course_material_metadata WHERE course_id=? AND filename=?",
                (course_id, filename),
            ).rowcount > 0
