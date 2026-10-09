"""Persisted weekly activities, private student completion, and course stars."""

from __future__ import annotations

import time
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException

from . import assignments
from .auth import AuthUser, get_current_user, require_role
from .courses import COURSE_CATALOG, _check_course_access, _visible_course_ids

router = APIRouter(tags=["course-structure"])

_SCHEMA = """
CREATE TABLE IF NOT EXISTS course_sections (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    week INTEGER NOT NULL CHECK(week > 0),
    title TEXT NOT NULL,
    UNIQUE(course_id, week)
);
CREATE TABLE IF NOT EXISTS course_activities (
    id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL REFERENCES course_sections(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK(type IN ('reading', 'video', 'quiz', 'assignment', 'discussion')),
    title TEXT NOT NULL,
    position INTEGER NOT NULL,
    assignment_id TEXT REFERENCES assignments(id) ON DELETE SET NULL,
    UNIQUE(section_id, position)
);
CREATE TABLE IF NOT EXISTS course_activity_completions (
    activity_id TEXT NOT NULL REFERENCES course_activities(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL,
    completed_at REAL NOT NULL,
    PRIMARY KEY(activity_id, student_id)
);
CREATE TABLE IF NOT EXISTS starred_courses (
    student_id INTEGER NOT NULL,
    course_id TEXT NOT NULL,
    starred_at REAL NOT NULL,
    PRIMARY KEY(student_id, course_id)
);
"""


@contextmanager
def _db(*, write: bool = False):
    with assignments._db() as conn:
        conn.executescript(_SCHEMA)
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()


def seed_demo_course_structure() -> dict[str, int]:
    """Seed three weeks for every catalog course after seed_demo_assignments().

    Existing activity titles and student work are preserved. A repeated seed
    also fills missing assignment links when assignments were seeded later.
    """
    sections_created = activities_created = assignment_links_updated = 0
    kinds = (
        ("reading", "課前閱讀"), ("video", "教學影片"), ("quiz", "概念測驗"),
        ("assignment", "實作作業"), ("discussion", "課堂討論"),
    )
    with _db(write=True) as conn:
        for course_id, course_name in COURSE_CATALOG.items():
            linked = conn.execute(
                "SELECT id FROM assignments WHERE course_id = ? ORDER BY due_at, id",
                (course_id,),
            ).fetchall()
            for week in range(1, 4):
                section_id = f"demo-section-{course_id}-{week}"
                sections_created += conn.execute(
                    "INSERT OR IGNORE INTO course_sections (id, course_id, week, title) "
                    "VALUES (?, ?, ?, ?)",
                    (section_id, course_id, week, f"第 {week} 週：{course_name}"),
                ).rowcount
                for position, (kind, title) in enumerate(kinds, start=1):
                    activity_id = f"demo-activity-{course_id}-{week}-{kind}"
                    assignment_id = (
                        linked[week - 1]["id"]
                        if kind == "assignment" and len(linked) >= week else None
                    )
                    activities_created += conn.execute(
                        "INSERT OR IGNORE INTO course_activities "
                        "(id, section_id, type, title, position, assignment_id) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (activity_id, section_id, kind, f"{course_name}：{title}",
                         position, assignment_id),
                    ).rowcount
                    if assignment_id is not None:
                        assignment_links_updated += conn.execute(
                            "UPDATE course_activities SET assignment_id = ? "
                            "WHERE id = ? AND assignment_id IS NULL",
                            (assignment_id, activity_id),
                        ).rowcount
    return {"sections_created": sections_created, "activities_created": activities_created,
            "assignment_links_updated": assignment_links_updated}


def _student_id(user: AuthUser) -> int:
    if user.moodle_user_id is None:
        raise HTTPException(403, "Student Moodle identity is required")
    return user.moodle_user_id


@router.get("/course-structure/{course_id}")
def course_structure(course_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    _check_course_access(user, course_id)
    student_id = _student_id(user) if user.role == "student" else None
    with _db() as conn:
        sections = conn.execute(
            "SELECT id, week, title FROM course_sections WHERE course_id = ? ORDER BY week",
            (course_id,),
        ).fetchall()
        activities = conn.execute(
            "SELECT a.id, a.section_id, a.type, a.title, a.assignment_id, "
            "c.completed_at FROM course_activities a "
            "JOIN course_sections s ON s.id = a.section_id "
            "LEFT JOIN course_activity_completions c ON c.activity_id = a.id "
            "AND c.student_id = ? WHERE s.course_id = ? ORDER BY s.week, a.position, a.id",
            (student_id, course_id),
        ).fetchall()
    grouped = {section["id"]: [] for section in sections}
    for row in activities:
        item = {key: row[key] for key in ("id", "type", "title", "assignment_id")}
        if user.role == "student":
            item.update(completed=row["completed_at"] is not None,
                        completed_at=row["completed_at"])
        grouped[row["section_id"]].append(item)
    return {"course_id": course_id, "sections": [
        dict(section) | {"activities": grouped[section["id"]]} for section in sections
    ]}


def _activity(conn, course_id: str, activity_id: str) -> None:
    exists = conn.execute(
        "SELECT 1 FROM course_activities a JOIN course_sections s ON s.id = a.section_id "
        "WHERE a.id = ? AND s.course_id = ?", (activity_id, course_id),
    ).fetchone()
    if exists is None:
        raise HTTPException(404, "Activity not found in this course")


@router.put("/course-structure/{course_id}/activities/{activity_id}/complete")
def complete_activity(
    course_id: str, activity_id: str,
    user: AuthUser = Depends(require_role("student")),
) -> dict:
    _check_course_access(user, course_id)
    student_id = _student_id(user)
    with _db(write=True) as conn:
        _activity(conn, course_id, activity_id)
        conn.execute(
            "INSERT OR IGNORE INTO course_activity_completions "
            "(activity_id, student_id, completed_at) VALUES (?, ?, ?)",
            (activity_id, student_id, time.time()),
        )
        completed_at = conn.execute(
            "SELECT completed_at FROM course_activity_completions "
            "WHERE activity_id = ? AND student_id = ?", (activity_id, student_id),
        ).fetchone()[0]
    return {"course_id": course_id, "activity_id": activity_id,
            "completed": True, "completed_at": completed_at}


@router.delete("/course-structure/{course_id}/activities/{activity_id}/complete")
def uncomplete_activity(
    course_id: str, activity_id: str,
    user: AuthUser = Depends(require_role("student")),
) -> dict:
    _check_course_access(user, course_id)
    with _db(write=True) as conn:
        _activity(conn, course_id, activity_id)
        conn.execute(
            "DELETE FROM course_activity_completions WHERE activity_id = ? AND student_id = ?",
            (activity_id, _student_id(user)),
        )
    return {"course_id": course_id, "activity_id": activity_id,
            "completed": False, "completed_at": None}


def _progress(student_id: int, total: int, completed: int) -> dict:
    return {"student_id": student_id, "completed": completed, "total": total,
            "percent": round(100 * completed / total, 2) if total else 0.0}


@router.get("/course-structure/{course_id}/progress")
def course_progress(course_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    _check_course_access(user, course_id)
    with _db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM course_activities a "
            "JOIN course_sections s ON s.id = a.section_id WHERE s.course_id = ?",
            (course_id,),
        ).fetchone()[0]
        counts = dict(conn.execute(
            "SELECT c.student_id, COUNT(*) FROM course_activity_completions c "
            "JOIN course_activities a ON a.id = c.activity_id "
            "JOIN course_sections s ON s.id = a.section_id "
            "WHERE s.course_id = ? GROUP BY c.student_id", (course_id,),
        ).fetchall())
        if user.role == "student":
            student_id = _student_id(user)
            return {"course_id": course_id} | _progress(
                student_id, total, counts.get(student_id, 0),
            )
        students = conn.execute(
            "SELECT DISTINCT moodle_user_id FROM chat_sessions "
            "WHERE course_id = ? ORDER BY moodle_user_id", (course_id,),
        ).fetchall()
    return {"course_id": course_id, "total": total, "students": [
        _progress(row[0], total, counts.get(row[0], 0)) for row in students
    ]}


@router.put("/me/starred-courses/{course_id}")
def star_course(course_id: str, user: AuthUser = Depends(require_role("student"))) -> dict:
    _check_course_access(user, course_id)
    with _db(write=True) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO starred_courses (student_id, course_id, starred_at) "
            "VALUES (?, ?, ?)", (_student_id(user), course_id, time.time()),
        )
    return {"course_id": course_id, "starred": True}


@router.delete("/me/starred-courses/{course_id}")
def unstar_course(course_id: str, user: AuthUser = Depends(require_role("student"))) -> dict:
    _check_course_access(user, course_id)
    with _db(write=True) as conn:
        conn.execute(
            "DELETE FROM starred_courses WHERE student_id = ? AND course_id = ?",
            (_student_id(user), course_id),
        )
    return {"course_id": course_id, "starred": False}


@router.get("/me/starred-courses")
def starred_courses(user: AuthUser = Depends(require_role("student"))) -> dict:
    visible = _visible_course_ids(user)
    with _db() as conn:
        rows = conn.execute(
            "SELECT course_id, starred_at FROM starred_courses WHERE student_id = ? "
            "ORDER BY starred_at DESC, course_id", (_student_id(user),),
        ).fetchall()
    return {"courses": [
        {"course_id": row["course_id"], "name": COURSE_CATALOG[row["course_id"]],
         "starred_at": row["starred_at"]}
        for row in rows if row["course_id"] in visible and row["course_id"] in COURSE_CATALOG
    ]}
