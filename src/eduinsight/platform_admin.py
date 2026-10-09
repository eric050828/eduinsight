"""Admin-only platform diagnostics and persisted audit events."""

from __future__ import annotations

import os
import platform
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from . import auth
from .auth import AuthUser, require_role
from .config import settings

router = APIRouter(prefix="/platform", tags=["platform"])


def _process_started_at() -> float:
    """Read OS process creation time without requiring psutil."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
                ctypes.POINTER(wintypes.FILETIME)
            ] * 4
            times = [wintypes.FILETIME() for _ in range(4)]
            if kernel.GetProcessTimes(kernel.GetCurrentProcess(), *map(ctypes.byref, times)):
                ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
                return ticks / 10_000_000 - 11_644_473_600
        elif Path("/proc/self/stat").exists():
            fields = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
            process_seconds = int(fields[19]) / os.sysconf("SC_CLK_TCK")
            system_seconds = float(Path("/proc/uptime").read_text().split()[0])
            return time.time() - system_seconds + process_seconds
    except (OSError, ValueError, AttributeError):
        pass
    # Other platforms can still supply exact process creation time via psutil.
    try:
        import psutil

        return psutil.Process().create_time()
    except (ImportError, OSError):
        return time.time()


_PROCESS_STARTED_AT = _process_started_at()


@contextmanager
def _db():
    with auth._db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS platform_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                demo_key TEXT UNIQUE
            );
            CREATE INDEX IF NOT EXISTS ix_platform_audit_ts
                ON platform_audit_log(ts DESC, id DESC);
        """)
        yield conn
        conn.commit()


def record_audit(actor: str, action: str, target: str) -> dict:
    """Persist an event from trusted backend code; actor is an account identifier."""
    with _db() as conn:
        cursor = conn.execute(
            "INSERT INTO platform_audit_log (ts, actor, action, target) VALUES (?, ?, ?, ?)",
            (time.time(), str(actor), action, target),
        )
        row = conn.execute(
            "SELECT id, ts, actor, action, target FROM platform_audit_log WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


def seed_demo_audit() -> int:
    """Create a few clearly marked demo events once, preserving real events."""
    entries = (
        ("demo.seed_users", "admin", "demo.users.seeded", "demo-users"),
        ("demo.seed_courses", "admin", "demo.courses.seeded", "course-catalog"),
        ("demo.seed_assignments", "teacher", "demo.assignments.seeded", "ds101"),
    )
    inserted = 0
    with _db() as conn:
        for key, actor, action, target in entries:
            inserted += conn.execute(
                "INSERT OR IGNORE INTO platform_audit_log "
                "(ts, actor, action, target, demo_key) VALUES (?, ?, ?, ?, ?)",
                (time.time(), actor, action, target, key),
            ).rowcount
    return inserted


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return {
        name: conn.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
        for (name,) in tables
    }


@router.get("/stats")
def platform_stats(user: AuthUser = Depends(require_role("admin"))) -> dict:
    with auth._db() as conn:
        counts = _row_counts(conn)
        roles = {"student": 0, "teacher": 0, "admin": 0}
        if "users" in counts:
            roles.update(dict(conn.execute("SELECT role, COUNT(*) FROM users GROUP BY role")))
        active_courses = 0
        if "chat_sessions" in counts:
            active_courses = conn.execute(
                "SELECT COUNT(DISTINCT course_id) FROM chat_sessions "
                "WHERE MAX(created_at, last_msg_at) >= ?",
                (time.time() - 30 * 86400,),
            ).fetchone()[0]
    return {
        "registered_users": roles,
        "total_users": sum(roles.values()),
        "active_courses": active_courses,
        "total_chat_sessions": counts.get("chat_sessions", 0),
        "total_assignments": counts.get("assignments", 0),
        "total_submissions": counts.get("assignment_submissions", 0),
    }


def _database_info(db_path: str) -> dict:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        return {"size_bytes": 0, "wal_size_bytes": 0, "row_counts": {}}
    # Read-only access never creates a missing Lite-Mem database or alters its schema.
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        counts = _row_counts(conn)
    finally:
        conn.close()
    wal = Path(str(path) + "-wal")
    return {
        "size_bytes": path.stat().st_size,
        "wal_size_bytes": wal.stat().st_size if wal.exists() else 0,
        "row_counts": counts,
    }


def _resource_info() -> tuple[dict | None, dict | None]:
    try:
        import psutil
    except ImportError:
        return None, None
    try:
        memory = psutil.virtual_memory()
        cpu = {"percent": psutil.cpu_percent(interval=None), "load_average": None}
        if hasattr(psutil, "getloadavg"):
            cpu["load_average"] = list(psutil.getloadavg())
        return cpu, {
            "total_bytes": memory.total, "available_bytes": memory.available,
            "used_bytes": memory.used, "percent": memory.percent,
            "process_rss_bytes": psutil.Process().memory_info().rss,
        }
    except (OSError, psutil.Error):
        return None, None


@router.get("/system")
def platform_system(user: AuthUser = Depends(require_role("admin"))) -> dict:
    cpu, memory = _resource_info()
    return {
        "uptime_seconds": max(0, time.time() - _PROCESS_STARTED_AT),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "databases": {
            "auth": _database_info(settings.auth_db_path),
            "memory": _database_info(settings.memory_db_path),
        },
        "cpu": cpu,
        "memory": memory,
    }


@router.get("/audit-log")
def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: AuthUser = Depends(require_role("admin")),
) -> dict:
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM platform_audit_log").fetchone()[0]
        entries = conn.execute(
            "SELECT id, ts, actor, action, target FROM platform_audit_log "
            "ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?", (limit, offset),
        ).fetchall()
    return {"entries": [dict(row) for row in entries], "total": total,
            "limit": limit, "offset": offset}
