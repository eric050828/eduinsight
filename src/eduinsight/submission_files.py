"""Real assignment attachments, independent of the text-submission router.

Storage defaults to <settings.auth_db_path parent>/uploads/assignments. Override
with EDUINSIGHT_SUBMISSION_UPLOAD_DIR (or a future settings.submission_upload_dir).
The text-submission owner can add ``files = list_submission_files(id, student_id)``
to response metadata. This helper is internal; callers must authorize first.
Uploads create a draft if necessary, preserving existing text and grade fields.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from . import assignments
from .auth import AuthUser, get_current_user, require_role
from .config import settings
from .db import schema_once

router = APIRouter(tags=["submission-files"])

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 5
ALLOWED_EXTENSIONS = frozenset("pdf doc docx ppt pptx xls xlsx txt md zip png jpg py ipynb".split())


def _ensure_table(conn: sqlite3.Connection) -> None:
    # Use execute rather than executescript: preserve the caller's transaction.
    conn.execute("""
            CREATE TABLE IF NOT EXISTS submission_files (
                id TEXT PRIMARY KEY,
                assignment_id TEXT NOT NULL,
                student_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size INTEGER NOT NULL CHECK(size >= 0 AND size <= 10485760),
                storage_path TEXT NOT NULL UNIQUE,
                uploaded_at REAL NOT NULL,
                FOREIGN KEY (assignment_id, student_id)
                    REFERENCES assignment_submissions(assignment_id, student_id)
                    ON DELETE CASCADE
            )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_submission_files_owner "
        "ON submission_files(assignment_id, student_id)"
    )


@contextmanager
def _db(*, write: bool = False):
    with assignments._db() as conn:
        with schema_once(conn, "submission_files") as initialize:
            if initialize:
                _ensure_table(conn)
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()


def upload_directory() -> Path:
    """Return the configured root; do not cache settings across resets/tests."""
    override = getattr(settings, "submission_upload_dir", None) or os.environ.get(
        "EDUINSIGHT_SUBMISSION_UPLOAD_DIR"
    )
    return (
        Path(override).expanduser()
        if override
        else Path(settings.auth_db_path).expanduser().resolve().parent / "uploads" / "assignments"
    ).resolve()


def _storage_path(relative: str) -> Path:
    # PureWindowsPath also detects drive-relative paths and UNC on POSIX hosts.
    if (
        not relative
        or "\\" in relative
        or ":" in relative
        or PureWindowsPath(relative).drive
        or Path(relative).is_absolute()
        or ".." in relative.split("/")
    ):
        raise HTTPException(400, "Unsafe attachment path")
    root = upload_directory()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise HTTPException(400, "Unsafe attachment path")
    return candidate


def _filename(value: str | None) -> str:
    if (
        not value
        or "/" in value
        or "\\" in value
        or ":" in value
        or value in {".", ".."}
        or any(ord(c) < 32 for c in value)
    ):
        raise HTTPException(400, "Unsafe filename")
    name = re.sub(r"[^\w. -]", "_", value, flags=re.UNICODE).strip(" .")
    if not name or len(name.encode("utf-8")) > 180:
        raise HTTPException(400, "Invalid filename or filename too long")
    extension = Path(name).suffix.lower().removeprefix(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "File extension is not allowed")
    if name.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = "_" + name
    return name


def _metadata(row) -> dict:
    result = {
        key: row[key]
        for key in (
            "id",
            "assignment_id",
            "student_id",
            "filename",
            "content_type",
            "size",
            "uploaded_at",
        )
    }
    result["download_url"] = f"/assignments/{row['assignment_id']}/submission/files/{row['id']}"
    return result


def list_submission_files(
    assignment_id: str,
    student_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> list[dict]:
    """Metadata only; authorize first. Pass connection inside a write transaction.

    Otherwise call after the owning transaction commits, to avoid a second
    connection attempting lazy schema creation while the caller holds a lock.
    """
    if connection is not None:
        # A caller-owned transaction may roll back: never commit it or cache
        # uncommitted DDL. Existing schemas need only a read, not repeated DDL.
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='submission_files'"
        ).fetchone() is None:
            _ensure_table(connection)
        return _list(connection, assignment_id, student_id)
    with _db() as conn:
        return _list(conn, assignment_id, student_id)


def _list(conn, assignment_id: str, student_id: int) -> list[dict]:
    return [
        _metadata(row)
        for row in conn.execute(
            "SELECT * FROM submission_files WHERE assignment_id = ? AND student_id = ? "
            "ORDER BY uploaded_at, id",
            (assignment_id, student_id),
        ).fetchall()
    ]


def _student_id(user: AuthUser) -> int:
    if user.moodle_user_id is None:
        raise HTTPException(403, "Student identity is required")
    return user.moodle_user_id


def _editable(conn, assignment_id: str, student_id: int) -> None:
    submission = assignments._submission(conn, assignment_id, student_id)
    if submission and submission["state"] == "graded":
        raise HTTPException(409, "Graded submissions cannot be changed")
    if submission and submission["state"] == "submitted":
        raise HTTPException(409, "Withdraw the submission before editing attachments")


def _authorize_assignment(assignment_id: str, user: AuthUser) -> dict:
    # Catalog initialization may write on a separate connection. Complete it
    # before acquiring our write lock. Assignment course IDs are immutable.
    with assignments._db() as conn:
        return assignments._assignment(conn, assignment_id, user)


def _file(conn, assignment_id: str, file_id: str, user: AuthUser):
    row = conn.execute(
        "SELECT * FROM submission_files WHERE id = ? AND assignment_id = ?",
        (file_id, assignment_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Attachment not found")
    if user.role == "student" and row["student_id"] != _student_id(user):
        raise HTTPException(403, "Attachment belongs to another student")
    return row


@router.post("/assignments/{assignment_id}/submission/files", status_code=201)
def upload_file(
    assignment_id: str,
    file: UploadFile = File(...),
    user: AuthUser = Depends(require_role("student")),
) -> dict:
    student_id = _student_id(user)
    destination = None
    created = False
    try:
        _authorize_assignment(assignment_id, user)
        # Preserve validation order and reject non-editable/full submissions
        # before disk staging. Repeat these checks under the write lock below.
        with _db() as conn:
            _editable(conn, assignment_id, student_id)
            if len(_list(conn, assignment_id, student_id)) >= MAX_FILES:
                raise HTTPException(409, "A submission can have at most five files")
        name = _filename(file.filename)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", assignment_id):
            raise HTTPException(400, "Unsafe assignment identifier")
        file_id = uuid.uuid4().hex
        relative = f"{assignment_id}/{student_id}/{file_id}_{name}"
        destination = _storage_path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = _storage_path(relative)  # Recheck after directory creation.
        size = 0
        with destination.open("xb") as out:
            created = True
            while chunk := file.file.read(64 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(413, "File exceeds the 10 MB limit")
                out.write(chunk)
        with _db(write=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM assignments WHERE id = ?",
                (assignment_id,),
            ).fetchone()
            if exists is None:
                raise HTTPException(404, "Assignment not found")
            _editable(conn, assignment_id, student_id)
            if len(_list(conn, assignment_id, student_id)) >= MAX_FILES:
                raise HTTPException(409, "A submission can have at most five files")
            now = time.time()
            conn.execute(
                "INSERT OR IGNORE INTO assignment_submissions "
                "(assignment_id, student_id, state, updated_at) VALUES (?, ?, 'draft', ?)",
                (assignment_id, student_id, now),
            )
            conn.execute(
                "INSERT INTO submission_files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_id,
                    assignment_id,
                    student_id,
                    name,
                    "application/octet-stream",
                    size,
                    relative,
                    now,
                ),
            )
            result = _metadata(
                conn.execute(
                    "SELECT * FROM submission_files WHERE id = ?",
                    (file_id,),
                ).fetchone()
            )
        return result
    except Exception:
        if created and destination is not None:
            destination.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()


@router.get("/assignments/{assignment_id}/submission/files")
def list_files(
    assignment_id: str,
    student_id: int | None = None,
    user: AuthUser = Depends(get_current_user),
) -> list[dict]:
    _authorize_assignment(assignment_id, user)
    with _db() as conn:
        if user.role == "student":
            own_id = _student_id(user)
            if student_id is not None and student_id != own_id:
                raise HTTPException(403, "Cannot list another student's files")
            student_id = own_id
        elif student_id is None:
            raise HTTPException(422, "Staff must specify student_id")
        return _list(conn, assignment_id, student_id)


@router.get("/assignments/{assignment_id}/submission/files/{file_id}")
def download_file(
    assignment_id: str,
    file_id: str,
    user: AuthUser = Depends(get_current_user),
) -> FileResponse:
    _authorize_assignment(assignment_id, user)
    with _db() as conn:
        row = _file(conn, assignment_id, file_id, user)
        path = _storage_path(row["storage_path"])
        if not path.is_file():
            raise HTTPException(404, "Attachment content not found")
        return FileResponse(
            path,
            filename=row["filename"],
            media_type="application/octet-stream",
            headers={"X-Content-Type-Options": "nosniff"},
        )


@router.delete("/assignments/{assignment_id}/submission/files/{file_id}", status_code=204)
def delete_file(
    assignment_id: str,
    file_id: str,
    user: AuthUser = Depends(require_role("student")),
) -> Response:
    _authorize_assignment(assignment_id, user)
    with _db(write=True) as conn:
        row = _file(conn, assignment_id, file_id, user)
        _editable(conn, assignment_id, _student_id(user))
        path = _storage_path(row["storage_path"])
        path.unlink(missing_ok=True)
        conn.execute("DELETE FROM submission_files WHERE id = ?", (file_id,))
    return Response(status_code=204)
