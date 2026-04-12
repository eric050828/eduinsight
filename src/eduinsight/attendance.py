"""Attendance / check-in management for classroom sessions.

Supports two check-in modes:
1. **Code-based** — Teacher starts session, students enter a 6-digit code.
2. **GPS-based** — Teacher sets a location, students must be within radius.

Usage::

    mgr = AttendanceManager()

    # Teacher opens a session
    session = mgr.create_session("CS101", teacher_id=1001)
    # session.checkin_code → "A3K9X2"

    # Student checks in
    record = mgr.checkin(session.session_id, student_id=2001)

    # Teacher closes
    mgr.close_session(session.session_id)

    # Stats
    stats = mgr.session_stats(session.session_id)
"""

from __future__ import annotations

import math
import random
import string
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class SessionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class CheckinStatus(StrEnum):
    PRESENT = "present"
    LATE = "late"


@dataclass
class GPSLocation:
    latitude: float
    longitude: float


@dataclass
class AttendanceSession:
    session_id: str
    course_id: str
    teacher_id: int
    title: str
    status: SessionStatus
    checkin_code: str
    created_at: float = field(default_factory=time.time)
    closed_at: float | None = None
    late_threshold_sec: int = 600  # 10 min default
    gps_location: GPSLocation | None = None
    gps_radius_m: float = 200.0  # metres


@dataclass
class CheckinRecord:
    student_id: int
    session_id: str
    status: CheckinStatus
    checked_in_at: float = field(default_factory=time.time)
    gps_location: GPSLocation | None = None


@dataclass
class AttendanceStats:
    session_id: str
    title: str
    status: SessionStatus
    total_checkins: int
    present_count: int
    late_count: int
    student_ids: list[int]


def _generate_code(length: int = 6) -> str:
    """Generate a random alphanumeric check-in code (uppercase, no ambiguous chars)."""
    chars = string.ascii_uppercase.replace("O", "").replace("I", "") + string.digits
    chars = chars.replace("0", "").replace("1", "")
    return "".join(random.choices(chars, k=length))


def _haversine_m(a: GPSLocation, b: GPSLocation) -> float:
    """Calculate distance in metres between two GPS coordinates."""
    R = 6_371_000  # Earth radius in metres
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = math.radians(b.latitude - a.latitude)
    dlon = math.radians(b.longitude - a.longitude)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(h))


class AttendanceManager:
    """In-memory manager for attendance sessions.

    Thread-safety note: single-process demo store.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, AttendanceSession] = {}
        self._records: dict[str, list[CheckinRecord]] = {}  # session_id → records

    # ── Session lifecycle ─────────────────────────────────────────

    def create_session(
        self,
        course_id: str,
        *,
        teacher_id: int,
        title: str = "",
        late_threshold_sec: int = 600,
        gps_location: GPSLocation | None = None,
        gps_radius_m: float = 200.0,
    ) -> AttendanceSession:
        """Create and immediately open an attendance session."""
        sid = f"att_{uuid.uuid4().hex[:12]}"
        code = _generate_code()
        session = AttendanceSession(
            session_id=sid,
            course_id=course_id,
            teacher_id=teacher_id,
            title=title or f"點名 {time.strftime('%H:%M')}",
            status=SessionStatus.OPEN,
            checkin_code=code,
            late_threshold_sec=late_threshold_sec,
            gps_location=gps_location,
            gps_radius_m=gps_radius_m,
        )
        self._sessions[sid] = session
        self._records[sid] = []
        return session

    def close_session(self, session_id: str) -> AttendanceSession:
        """Close the session — no more check-ins.

        Raises:
            KeyError: If session not found.
            ValueError: If already closed.
        """
        session = self._get_session(session_id)
        if session.status == SessionStatus.CLOSED:
            raise ValueError("Session is already closed")
        session.status = SessionStatus.CLOSED
        session.closed_at = time.time()
        return session

    def get_session(self, session_id: str) -> AttendanceSession:
        """Get session by ID.

        Raises:
            KeyError: If not found.
        """
        return self._get_session(session_id)

    def find_session_by_code(self, code: str) -> AttendanceSession | None:
        """Find an open session by its check-in code (case-insensitive)."""
        code_upper = code.upper()
        for session in self._sessions.values():
            if (
                session.status == SessionStatus.OPEN
                and session.checkin_code == code_upper
            ):
                return session
        return None

    def list_sessions(self, course_id: str | None = None) -> list[AttendanceSession]:
        """List sessions, optionally filtered by course."""
        sessions = list(self._sessions.values())
        if course_id:
            sessions = [s for s in sessions if s.course_id == course_id]
        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    # ── Check-in ─────────────────────────────────────────────────

    def checkin(
        self,
        session_id: str,
        *,
        student_id: int,
        code: str | None = None,
        gps_location: GPSLocation | None = None,
    ) -> CheckinRecord:
        """Student checks in to a session.

        Args:
            session_id: The attendance session.
            student_id: Student performing check-in.
            code: Check-in code (validated against session code).
            gps_location: Student's GPS for proximity check.

        Raises:
            KeyError: If session not found.
            ValueError: If session closed, code wrong, or GPS out of range.
        """
        session = self._get_session(session_id)

        if session.status != SessionStatus.OPEN:
            raise ValueError("Session is closed, check-in not allowed")

        # Code validation
        if code is not None and code.upper() != session.checkin_code:
            raise ValueError("Invalid check-in code")

        # GPS validation
        if session.gps_location and gps_location:
            dist = _haversine_m(session.gps_location, gps_location)
            if dist > session.gps_radius_m:
                raise ValueError(
                    f"Too far from classroom ({dist:.0f}m, max {session.gps_radius_m:.0f}m)"
                )

        # Duplicate check — update existing record
        records = self._records[session_id]
        for rec in records:
            if rec.student_id == student_id:
                return rec  # already checked in

        # Determine present vs late
        elapsed = time.time() - session.created_at
        status = (
            CheckinStatus.LATE
            if elapsed > session.late_threshold_sec
            else CheckinStatus.PRESENT
        )

        record = CheckinRecord(
            student_id=student_id,
            session_id=session_id,
            status=status,
            gps_location=gps_location,
        )
        records.append(record)
        return record

    def get_records(self, session_id: str) -> list[CheckinRecord]:
        """Get all check-in records for a session.

        Raises:
            KeyError: If session not found.
        """
        self._get_session(session_id)  # validate exists
        return list(self._records.get(session_id, []))

    # ── Stats ────────────────────────────────────────────────────

    def session_stats(self, session_id: str) -> AttendanceStats:
        """Get attendance statistics for a session.

        Raises:
            KeyError: If session not found.
        """
        session = self._get_session(session_id)
        records = self._records.get(session_id, [])
        present = sum(1 for r in records if r.status == CheckinStatus.PRESENT)
        late = sum(1 for r in records if r.status == CheckinStatus.LATE)
        return AttendanceStats(
            session_id=session.session_id,
            title=session.title,
            status=session.status,
            total_checkins=len(records),
            present_count=present,
            late_count=late,
            student_ids=[r.student_id for r in records],
        )

    def student_history(
        self, student_id: int, course_id: str | None = None
    ) -> list[dict]:
        """Get a student's attendance history across sessions.

        Returns list of dicts with session info + checkin status.
        """
        result = []
        for session in self._sessions.values():
            if course_id and session.course_id != course_id:
                continue
            records = self._records.get(session.session_id, [])
            for rec in records:
                if rec.student_id == student_id:
                    result.append(
                        {
                            "session_id": session.session_id,
                            "course_id": session.course_id,
                            "title": session.title,
                            "status": rec.status.value,
                            "checked_in_at": rec.checked_in_at,
                            "session_created_at": session.created_at,
                        }
                    )
                    break
        return sorted(result, key=lambda x: x["session_created_at"], reverse=True)

    # ── Internal ─────────────────────────────────────────────────

    def _get_session(self, session_id: str) -> AttendanceSession:
        if session_id not in self._sessions:
            raise KeyError(f"Attendance session '{session_id}' not found")
        return self._sessions[session_id]
