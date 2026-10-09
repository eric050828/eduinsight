"""Authenticated course catalog backed by chat-session enrollment."""

from __future__ import annotations

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


class CourseParticipant(BaseModel):
    display_name: str
    role: str
    username: str
    last_active: float | None


def _visible_course_ids(user: AuthUser) -> set[str]:
    if user.role == "admin":
        return set(COURSE_CATALOG)
    if user.role == "teacher":
        owned = TEACHER_COURSE_MAP.get(user.username)
        return {owned} if owned is not None else set()
    if user.moodle_user_id is None:
        return set()
    with sessions._db() as conn:  # noqa: SLF001
        rows = conn.execute(
            "SELECT DISTINCT course_id FROM chat_sessions WHERE moodle_user_id = ?",
            (user.moodle_user_id,),
        ).fetchall()
    return {row["course_id"] for row in rows}


def _check_course_access(user: AuthUser, course_id: str) -> None:
    if course_id not in COURSE_CATALOG:
        raise HTTPException(status_code=404, detail="Course not found")
    if course_id not in _visible_course_ids(user):
        raise HTTPException(status_code=403, detail="Course access denied")


def _teacher_username(course_id: str) -> str | None:
    return next(
        (username for username, owned in TEACHER_COURSE_MAP.items() if owned == course_id),
        None,
    )


def _course_info(course_id: str) -> CourseInfo:
    teacher_username = _teacher_username(course_id)
    with sessions._db() as conn:  # noqa: SLF001
        teacher = conn.execute(
            "SELECT display_name FROM users WHERE username = ? AND role = 'teacher'",
            (teacher_username,),
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(DISTINCT moodle_user_id) FROM chat_sessions WHERE course_id = ?",
            (course_id,),
        ).fetchone()[0]
    return CourseInfo(
        id=course_id,
        name=COURSE_CATALOG[course_id],
        teacher_username=teacher_username,
        teacher_name=teacher["display_name"] if teacher is not None else None,
        enrolled_count=count,
    )


@router.get("", response_model=list[CourseInfo])
async def list_courses(user: AuthUser = Depends(get_current_user)) -> list[CourseInfo]:
    visible = _visible_course_ids(user)
    return [_course_info(course_id) for course_id in COURSE_CATALOG if course_id in visible]


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
            "SELECT display_name, role, username, moodle_user_id FROM users "
            "WHERE username = ? AND role = 'teacher'",
            (_teacher_username(course_id),),
        ).fetchone()
        students = conn.execute(
            "SELECT u.display_name, u.role, u.username, u.moodle_user_id, "
            "MAX(MAX(s.created_at, s.last_msg_at)) AS last_active "
            "FROM users u JOIN chat_sessions s ON s.moodle_user_id = u.moodle_user_id "
            "WHERE s.course_id = ? AND u.role = 'student' "
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
        if row["moodle_user_id"] is not None:
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
            display_name=row["display_name"],
            role=row["role"],
            username=row["username"],
            last_active=last_active,
        ))
    return participants
