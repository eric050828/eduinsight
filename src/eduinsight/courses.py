"""Course catalog and authoritative enrollment, with one-time legacy migration."""

from __future__ import annotations

from contextlib import contextmanager
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import sessions
from .auth import TEACHER_COURSE_MAP, AuthUser, get_current_user

router = APIRouter(prefix="/courses", tags=["courses"])

COURSE_CATALOG: dict[str, str] = {
    "general": "一般課程",
    "ds101": "資料結構",
    "py101": "Python 程式設計",
    "db101": "資料庫系統",
    "mk201": "行銷管理",
    "chm301": "化學",
    "eng201": "英文閱讀與表達",
    "ipr101": "智慧財產權",
}


class CourseInfo(BaseModel):
    id: str
    name: str
    teacher_username: str | None
    teacher_name: str | None
    enrolled_count: int
    description: str = ""
    archived: bool = False


class CourseParticipant(BaseModel):
    user_id: int
    moodle_user_id: int | None
    display_name: str
    role: str
    username: str
    last_active: float | None


@contextmanager
def _catalog_db():
    """Static assignments are seed data only; persisted assignments take precedence."""
    with sessions._db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS course_catalog (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                teacher_username TEXT,
                description TEXT NOT NULL DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1))
            );
        """)
        for course_id, name in COURSE_CATALOG.items():
            teacher = next((username for username, owned in TEACHER_COURSE_MAP.items()
                            if owned == course_id), None)
            conn.execute("INSERT OR IGNORE INTO course_catalog (id, name, teacher_username) "
                         "VALUES (?, ?, ?)", (course_id, name, teacher))
        conn.commit()
        yield conn
        conn.commit()


def catalog_entries() -> dict[str, dict]:
    with _catalog_db() as conn:
        return {row["id"]: dict(row) for row in conn.execute("SELECT * FROM course_catalog")}


def init_enrollments() -> None:
    """Backfill existing sessions exactly once, when the enrollment table is created.

    Deployments must review legacy enrollments: old forged sessions cannot be
    distinguished from legitimate enrollment without an external roster.
    """
    sessions.init_sessions_table()
    with sessions._db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='course_enrollments'").fetchone()
        conn.execute("""CREATE TABLE IF NOT EXISTS course_enrollments (
            course_id TEXT NOT NULL, moodle_user_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'student', source TEXT NOT NULL,
            created_at REAL NOT NULL, UNIQUE(course_id, moodle_user_id))""")
        if not exists:
            conn.execute("INSERT OR IGNORE INTO course_enrollments "
                         "SELECT course_id, moodle_user_id, 'student', 'legacy_sessions', "
                         "MIN(created_at) FROM chat_sessions GROUP BY course_id, moodle_user_id")
        conn.commit()
    catalog_entries()


def is_enrolled(course_id: str, moodle_user_id: int | None, *, conn=None) -> bool:
    if moodle_user_id is None:
        return False
    if course_id == "general":
        return True
    if conn is None:
        with sessions._db() as db:
            return is_enrolled(course_id, moodle_user_id, conn=db)
    return conn.execute("SELECT 1 FROM course_enrollments WHERE course_id=? AND moodle_user_id=?",
                        (course_id, moodle_user_id)).fetchone() is not None


def enroll(course_id: str, moodle_user_id: int, role: str = "student",
           source: str = "manual", *, conn=None) -> None:
    if conn is None:
        with sessions._db() as db:
            enroll(course_id, moodle_user_id, role, source, conn=db)
            db.commit()
        return
    conn.execute("INSERT OR IGNORE INTO course_enrollments "
                 "(course_id, moodle_user_id, role, source, created_at) VALUES (?, ?, ?, ?, ?)",
                 (course_id, moodle_user_id, role, source, time.time()))


def list_enrolled(course_id: str) -> set[int]:
    with sessions._db() as conn:
        return {row[0] for row in conn.execute(
            "SELECT moodle_user_id FROM course_enrollments WHERE course_id=? AND role='student'",
            (course_id,))}


def _catalog_snapshot() -> dict[str, dict]:
    """Read-only lookup, including inside another module's write transaction."""
    with sessions._db() as conn:
        return {row["id"]: dict(row) for row in conn.execute("SELECT * FROM course_catalog")}


def _visible_course_ids(user: AuthUser) -> set[str]:
    catalog = _catalog_snapshot()
    if user.role == "admin":
        return set(catalog)
    if user.role == "teacher":
        return {cid for cid, row in catalog.items() if row["teacher_username"] == user.username}
    if user.moodle_user_id is None:
        return set()
    with sessions._db() as conn:  # noqa: SLF001
        rows = conn.execute(
            "SELECT DISTINCT course_id FROM course_enrollments WHERE moodle_user_id = ?",
            (user.moodle_user_id,),
        ).fetchall()
    return {"general"} | {row["course_id"] for row in rows}


def _check_course_access(user: AuthUser, course_id: str) -> None:
    if course_id not in _catalog_snapshot():
        raise HTTPException(status_code=404, detail="Course not found")
    if course_id not in _visible_course_ids(user):
        raise HTTPException(status_code=403, detail="Course access denied")


def _teacher_username(course_id: str) -> str | None:
    row = _catalog_snapshot().get(course_id)
    return row["teacher_username"] if row else None


def _course_info(course_id: str) -> CourseInfo:
    entry = catalog_entries()[course_id]
    teacher_username = entry["teacher_username"]
    with sessions._db() as conn:  # noqa: SLF001
        teacher = conn.execute(
            "SELECT display_name FROM users WHERE username = ? AND role = 'teacher'",
            (teacher_username,),
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(DISTINCT moodle_user_id) FROM course_enrollments WHERE course_id = ?",
            (course_id,),
        ).fetchone()[0]
    return CourseInfo(
        id=course_id,
        name=entry["name"],
        teacher_username=teacher_username,
        teacher_name=teacher["display_name"] if teacher is not None else None,
        enrolled_count=count,
        description=entry["description"],
        archived=bool(entry["archived"]),
    )


@router.get("", response_model=list[CourseInfo])
async def list_courses(user: AuthUser = Depends(get_current_user)) -> list[CourseInfo]:
    visible = _visible_course_ids(user)
    return [_course_info(course_id) for course_id in catalog_entries() if course_id in visible]


@router.get("/{course_id}/info", response_model=CourseInfo)
async def course_info(
    course_id: str, user: AuthUser = Depends(get_current_user),
) -> CourseInfo:
    _check_course_access(user, course_id)
    return _course_info(course_id)


@router.get("/{course_id}/participants", response_model=list[CourseParticipant])
async def course_participants(
    course_id: str, user: AuthUser = Depends(get_current_user),
) -> list[CourseParticipant]:
    _check_course_access(user, course_id)
    with sessions._db() as conn:  # noqa: SLF001
        teacher = conn.execute(
            "SELECT id, display_name, role, username, moodle_user_id FROM users "
            "WHERE username = ? AND role = 'teacher'",
            (_teacher_username(course_id),),
        ).fetchone()
        students = conn.execute(
            "SELECT u.id, u.display_name, u.role, u.username, u.moodle_user_id, "
            "MAX(MAX(s.created_at, s.last_msg_at)) AS last_active "
            "FROM users u JOIN course_enrollments e ON e.moodle_user_id = u.moodle_user_id LEFT JOIN chat_sessions s ON s.moodle_user_id = e.moodle_user_id AND s.course_id = e.course_id "
            "WHERE e.course_id = ? AND u.role = 'student' "
            "GROUP BY u.id ORDER BY u.username",
            (course_id,),
        ).fetchall()

    # Resolve shared memory only after authentication and course authorization.
    # Lite-Mem facts are per user (not per course), as in the teacher dashboard.
    from .app import get_assistant

    memory_conn = get_assistant().memory._store._get_conn()  # noqa: SLF001
    participants = []
    for row in ([teacher] if teacher is not None else []) + list(students):
        last_active = row["last_active"] if row["role"] == "student" else None
        if row["role"] == "student" and row["moodle_user_id"] is not None:
            uid = f"moodle:{row['moodle_user_id']}"
            memory_active = memory_conn.execute(
                "SELECT MAX(ts) FROM ("
                "SELECT MAX(created_at, updated_at) AS ts FROM facts WHERE user_id = ? "
                "UNION ALL SELECT created_at AS ts FROM messages WHERE user_id = ?)",
                (uid, uid),
            ).fetchone()[0]
            timestamps = [ts for ts in (last_active, memory_active) if ts is not None]
            last_active = max(timestamps) if timestamps else None
        participants.append(CourseParticipant(
            user_id=row["id"],
            moodle_user_id=row["moodle_user_id"] if row["role"] == "student" else None,
            display_name=row["display_name"],
            role=row["role"],
            username=row["username"],
            last_active=last_active,
        ))
    return participants
