"""Computed student badges, profile statistics and a private persisted calendar.

No achievement seed is required. Empty chat sessions do not earn chat badges;
five chats means five user messages. Badge timestamps are evidence timestamps,
not the time this endpoint was called. No synthetic demo activity is inserted.
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from . import analytics_extra as extra
from . import assignments, course_structure, sessions
from .analytics_extra import _messages, _timestamp
from .auth import AuthUser, require_role
from .class_analytics import _activity_stamps, _own_course_ids, _weekly

router = APIRouter(tags=["achievements"])

_BADGES = (
    ("first_submission", "初次繳交", "繳交第一份作業。", 1),
    ("on_time_three", "準時達人", "準時繳交三份作業。", 3),
    ("perfect_score", "滿分表現", "一項作業或成績項目獲得滿分。", 1),
    ("first_ai_chat", "AI 初體驗", "傳送第一則 AI 聊天訊息。", 1),
    ("five_ai_chats", "AI 探索者", "傳送五則 AI 聊天訊息。", 5),
    ("seven_day_streak", "持續學習", "連續七天有學習活動。", 7),
    ("first_forum_post", "交流起步", "發表第一篇討論區貼文。", 1),
    ("half_course", "學習過半", "完成任一已註冊課程至少一半的活動。", 50),
)


def _student_id(user: AuthUser) -> int:
    if user.moodle_user_id is None:
        raise HTTPException(403, "Student Moodle identity is required")
    return user.moodle_user_id


def _iso(value: object) -> str | None:
    ts = _timestamp(value)
    if ts is None or ts <= 0 or ts > extra._now().timestamp():
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat()


def _own_rows(user: AuthUser) -> tuple[list[str], list[dict], list[dict]]:
    sid = _student_id(user)
    courses = sorted(_own_course_ids(user))
    with sessions._db() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM chat_sessions WHERE moodle_user_id = ? ORDER BY session_id", (sid,),
        ) if row["course_id"] in courses]
    messages = _messages(extra.get_memory(), sid, rows, scoped=True) if rows else []
    return courses, rows, messages


def _forum_posts(user: AuthUser, courses: list[str]) -> list[dict]:
    """Optional forum storage: forum.py authors use auth IDs, not Moodle IDs.

    Unknown schemas have no safe ownership semantics, so return no evidence.
    Importing a forum router to inspect data would create an unnecessary cycle.
    """
    with sessions._db() as conn:
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(forum_posts)")}
            owner = next((name for name in ("author_id", "student_id", "moodle_user_id")
                          if name in columns), None)
            if not owner:
                return []
            identity = user.id if owner == "author_id" else _student_id(user)
            if "course_id" in columns:
                rows = conn.execute(f"SELECT * FROM forum_posts WHERE {owner} = ?",
                                    (identity,)).fetchall()
            elif "thread_id" in columns:
                rows = conn.execute(
                    f"SELECT p.*, t.course_id FROM forum_posts p "
                    f"JOIN forum_threads t ON t.id = p.thread_id WHERE p.{owner} = ?",
                    (identity,),
                ).fetchall()
            else:
                return []
            return [dict(row) for row in rows if row["course_id"] in courses]
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc) or "no such column" in str(exc):
                return []
            raise


def _course_completion(sid: int, courses: list[str]) -> list[dict]:
    result = []
    with course_structure._db() as conn:
        for course_id in courses:
            total = conn.execute(
                "SELECT COUNT(*) FROM course_activities a JOIN course_sections s ON s.id = a.section_id "
                "WHERE s.course_id = ?", (course_id,),
            ).fetchone()[0]
            stamps = [row[0] for row in conn.execute(
                "SELECT c.completed_at FROM course_activity_completions c "
                "JOIN course_activities a ON a.id = c.activity_id "
                "JOIN course_sections s ON s.id = a.section_id "
                "WHERE c.student_id = ? AND s.course_id = ? ORDER BY c.completed_at, a.id",
                (sid, course_id),
            ) if _iso(row[0]) is not None]
            result.append({"course_id": course_id, "total": total, "completed": len(stamps),
                           "percent": round(100 * len(stamps) / total, 2) if total else 0,
                           "stamps": stamps})
    return result


def _evidence(user: AuthUser) -> dict:
    sid = _student_id(user)
    courses, rows, messages = _own_rows(user)
    with assignments._db() as conn:
        submissions = [dict(row) for row in conn.execute(
            "SELECT s.*, a.course_id, a.max_score FROM assignment_submissions s "
            "JOIN assignments a ON a.id = s.assignment_id "
            "WHERE s.student_id = ? AND s.state IN ('submitted', 'graded')", (sid,),
        ) if row["course_id"] in courses and _iso(row["submitted_at"]) is not None]
    completion = _course_completion(sid, courses)
    posts = _forum_posts(user, courses)
    forum_stamps = sorted(row["created_at"] for row in posts if _iso(row.get("created_at")))
    submit_stamps = sorted(row["submitted_at"] for row in submissions)
    on_time = sorted(row["submitted_at"] for row in submissions if not row["late"])
    chat_stamps = sorted(ts for message in messages
                         if _iso(ts := message["created_at"]) is not None)
    perfect = [row["graded_at"] for row in submissions if row["state"] == "graded"
               and row["score"] == row["max_score"] and _iso(row["graded_at"])]
    manager = extra.get_grade_manager()
    for course_id in courses:
        for record in manager.get_scores(course_id, student_id=sid):
            stamp = _timestamp(getattr(record, "created_at", None))
            if (record.total > 0 and record.score == record.total
                    and (stamp is None or stamp == 0 or 0 < stamp <= extra._now().timestamp())):
                perfect.append(stamp)
    perfect.sort(key=lambda stamp: _timestamp(stamp) or float("inf"))
    activity = _activity_stamps(rows, messages) + submit_stamps + forum_stamps
    activity.extend(stamp for course in completion for stamp in course["stamps"])
    dates = sorted({datetime.fromtimestamp(stamp, extra._TAIPEI).date() for stamp in activity})
    current = longest = 0
    previous = None
    streak_earned = None
    for day in dates:
        current = current + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, current)
        if current == 7 and streak_earned is None:
            streak_earned = min(stamp for stamp in activity
                                if datetime.fromtimestamp(stamp, extra._TAIPEI).date() == day)
        previous = day
    half_stamps = [course["stamps"][math.ceil(course["total"] / 2) - 1]
                   for course in completion if course["total"] > 0
                   and course["completed"] >= math.ceil(course["total"] / 2)]
    progress = max((100 * course["completed"] / course["total"]
                    for course in completion if course["total"]), default=0)
    values = {
        "first_submission": (len(submit_stamps), submit_stamps[0] if submit_stamps else None),
        "on_time_three": (len(on_time), on_time[2] if len(on_time) >= 3 else None),
        "perfect_score": (len(perfect), perfect[0] if perfect else None),
        "first_ai_chat": (len(chat_stamps), chat_stamps[0] if chat_stamps else None),
        "five_ai_chats": (len(chat_stamps), chat_stamps[4] if len(chat_stamps) >= 5 else None),
        "seven_day_streak": (longest, streak_earned),
        "first_forum_post": (len(posts), forum_stamps[0] if forum_stamps else None),
        "half_course": (progress, min(half_stamps) if half_stamps else None),
    }
    return {"values": values, "completion": completion, "posts": posts,
            "rows": rows, "messages": messages}


def _badges(evidence: dict) -> dict:
    earned, locked = [], []
    for badge_id, title, description, target in _BADGES:
        current, stamp = evidence["values"][badge_id]
        badge = {"id": badge_id, "title": title, "description": description}
        if current >= target:
            earned.append(badge | {"earned_at": _iso(stamp)})
        else:
            locked.append(badge | {"progress": {"current": round(current, 2), "target": target,
                                                "percent": round(100 * current / target, 2)}})
    return {"earned": earned, "locked": locked}


@router.get("/me/achievements")
def achievements(user: AuthUser = Depends(require_role("student"))) -> dict:
    return _badges(_evidence(user))


@router.get("/me/profile-stats")
def profile_stats(user: AuthUser = Depends(require_role("student"))) -> dict:
    evidence = _evidence(user)
    complete = [course["course_id"] for course in evidence["completion"]
                if course["total"] > 0 and course["completed"] == course["total"]]
    weeks = _weekly(evidence["rows"], evidence["messages"])
    return {"completed_courses": len(complete), "completed_course_ids": complete,
            "badges_count": len(_badges(evidence)["earned"]),
            "estimated_learning_hours": round(sum(week["hours"] for week in weeks), 4),
            "hours_period_weeks": 8, "estimated": True, "forum_posts": len(evidence["posts"])}


@contextmanager
def _calendar_db(*, write: bool = False):
    with assignments._db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS student_calendar_events (
                id TEXT PRIMARY KEY,
                student_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                start REAL NOT NULL,
                end REAL,
                notes TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS ix_student_calendar_owner
                ON student_calendar_events(student_id, start);
        """)
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()


class CalendarEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    start: AwareDatetime
    end: AwareDatetime | None = None
    notes: str = Field(default="", max_length=20000)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.end is not None and self.end < self.start:
            raise ValueError("End must not precede start")
        return self


def _event_view(row: dict) -> dict:
    return {"id": row["id"], "source": "custom", "title": row["title"],
            "start": datetime.fromtimestamp(row["start"], UTC).isoformat(),
            "end": datetime.fromtimestamp(row["end"], UTC).isoformat()
            if row["end"] is not None else None,
            "notes": row["notes"]}


@router.get("/me/calendar")
def calendar(user: AuthUser = Depends(require_role("student"))) -> dict:
    sid = _student_id(user)
    courses = _own_course_ids(user)
    with _calendar_db() as conn:
        events = [_event_view(dict(row)) for row in conn.execute(
            "SELECT * FROM student_calendar_events WHERE student_id = ? ORDER BY start, id", (sid,),
        )]
        for course_id in sorted(courses):
            for row in conn.execute("SELECT * FROM assignments WHERE course_id = ?", (course_id,)):
                events.append({"id": f"assignment:{row['id']}", "source": "assignment",
                               "assignment_id": row["id"], "course_id": course_id,
                               "title": row["title"],
                               "start": datetime.fromtimestamp(row["due_at"], UTC).isoformat(),
                               "end": None, "notes": row["description"]})
    events.sort(key=lambda event: (datetime.fromisoformat(event["start"]), event["id"]))
    return {"timezone": "Asia/Taipei", "events": events}


@router.post("/me/calendar/events", status_code=201)
def create_event(body: CalendarEventCreate, user: AuthUser = Depends(require_role("student"))) -> dict:
    row = {"id": f"calendar-{uuid.uuid4().hex}", "student_id": _student_id(user),
           "title": body.title, "start": body.start.timestamp(),
           "end": body.end.timestamp() if body.end else None, "notes": body.notes}
    with _calendar_db(write=True) as conn:
        conn.execute("INSERT INTO student_calendar_events (id, student_id, title, start, end, notes) "
                     "VALUES (:id, :student_id, :title, :start, :end, :notes)", row)
    return _event_view(row)


@router.put("/me/calendar/events/{event_id}")
def update_event(event_id: str, body: CalendarEventCreate,
                 user: AuthUser = Depends(require_role("student"))) -> dict:
    sid = _student_id(user)
    with _calendar_db(write=True) as conn:
        row = conn.execute("SELECT * FROM student_calendar_events WHERE id = ? AND student_id = ?",
                           (event_id, sid)).fetchone()
        if row is None:
            raise HTTPException(404, "Calendar event not found")
        conn.execute("UPDATE student_calendar_events SET title = ?, start = ?, end = ?, notes = ? "
                     "WHERE id = ? AND student_id = ?",
                     (body.title, body.start.timestamp(), body.end.timestamp() if body.end else None,
                      body.notes, event_id, sid))
        return _event_view(dict(conn.execute("SELECT * FROM student_calendar_events WHERE id = ?",
                                            (event_id,)).fetchone()))


@router.delete("/me/calendar/events/{event_id}", status_code=204)
def delete_event(event_id: str, user: AuthUser = Depends(require_role("student"))) -> Response:
    with _calendar_db(write=True) as conn:
        deleted = conn.execute("DELETE FROM student_calendar_events WHERE id = ? AND student_id = ?",
                               (event_id, _student_id(user))).rowcount
        if not deleted:
            raise HTTPException(404, "Calendar event not found")
    return Response(status_code=204)
