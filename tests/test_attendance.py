"""Tests for attendance / check-in system."""

from __future__ import annotations

import pytest

from eduinsight.attendance import (
    AttendanceManager,
    CheckinStatus,
    GPSLocation,
    SessionStatus,
    _haversine_m,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def mgr() -> AttendanceManager:
    return AttendanceManager()


# ------------------------------------------------------------------
# Session lifecycle
# ------------------------------------------------------------------


class TestSessionLifecycle:
    def test_create_session(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        assert s.session_id.startswith("att_")
        assert s.status == SessionStatus.OPEN
        assert len(s.checkin_code) == 6
        assert s.course_id == "CS101"

    def test_create_with_title(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001, title="Week 5")
        assert s.title == "Week 5"

    def test_close_session(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        closed = mgr.close_session(s.session_id)
        assert closed.status == SessionStatus.CLOSED
        assert closed.closed_at is not None

    def test_close_already_closed_raises(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        mgr.close_session(s.session_id)
        with pytest.raises(ValueError, match="already closed"):
            mgr.close_session(s.session_id)

    def test_get_nonexistent_session(self, mgr: AttendanceManager):
        with pytest.raises(KeyError):
            mgr.get_session("nonexistent")

    def test_list_sessions(self, mgr: AttendanceManager):
        mgr.create_session("CS101", teacher_id=1001)
        mgr.create_session("CS201", teacher_id=1001)
        mgr.create_session("CS101", teacher_id=1001)
        assert len(mgr.list_sessions()) == 3
        assert len(mgr.list_sessions("CS101")) == 2

    def test_find_by_code(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        found = mgr.find_session_by_code(s.checkin_code)
        assert found is not None
        assert found.session_id == s.session_id

    def test_find_by_code_case_insensitive(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        found = mgr.find_session_by_code(s.checkin_code.lower())
        assert found is not None

    def test_find_by_code_closed_returns_none(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        mgr.close_session(s.session_id)
        assert mgr.find_session_by_code(s.checkin_code) is None

    def test_find_by_code_nonexistent(self, mgr: AttendanceManager):
        assert mgr.find_session_by_code("ZZZZZZ") is None


# ------------------------------------------------------------------
# Check-in
# ------------------------------------------------------------------


class TestCheckin:
    def test_basic_checkin(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        rec = mgr.checkin(s.session_id, student_id=2001)
        assert rec.student_id == 2001
        assert rec.status == CheckinStatus.PRESENT

    def test_checkin_with_valid_code(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        rec = mgr.checkin(s.session_id, student_id=2001, code=s.checkin_code)
        assert rec.status == CheckinStatus.PRESENT

    def test_checkin_with_wrong_code(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        with pytest.raises(ValueError, match="Invalid check-in code"):
            mgr.checkin(s.session_id, student_id=2001, code="WRONG1")

    def test_checkin_closed_session(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        mgr.close_session(s.session_id)
        with pytest.raises(ValueError, match="closed"):
            mgr.checkin(s.session_id, student_id=2001)

    def test_duplicate_checkin_returns_existing(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        r1 = mgr.checkin(s.session_id, student_id=2001)
        r2 = mgr.checkin(s.session_id, student_id=2001)
        assert r1.checked_in_at == r2.checked_in_at  # same record

    def test_late_checkin(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001, late_threshold_sec=0)
        # threshold=0 means any delay is late
        rec = mgr.checkin(s.session_id, student_id=2001)
        assert rec.status == CheckinStatus.LATE

    def test_multiple_students(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        mgr.checkin(s.session_id, student_id=2001)
        mgr.checkin(s.session_id, student_id=2002)
        mgr.checkin(s.session_id, student_id=2003)
        records = mgr.get_records(s.session_id)
        assert len(records) == 3

    def test_get_records_nonexistent(self, mgr: AttendanceManager):
        with pytest.raises(KeyError):
            mgr.get_records("nonexistent")


# ------------------------------------------------------------------
# GPS
# ------------------------------------------------------------------


class TestGPS:
    def test_haversine_same_point(self):
        a = GPSLocation(25.0330, 121.5654)
        assert _haversine_m(a, a) == 0.0

    def test_haversine_known_distance(self):
        # Taipei Main Station to NTUST (~2.5km)
        a = GPSLocation(25.0478, 121.5170)
        b = GPSLocation(25.0130, 121.5413)
        dist = _haversine_m(a, b)
        assert 4000 < dist < 5000  # ~4.5km

    def test_gps_checkin_within_radius(self, mgr: AttendanceManager):
        loc = GPSLocation(25.0330, 121.5654)
        s = mgr.create_session(
            "CS101", teacher_id=1001, gps_location=loc, gps_radius_m=500
        )
        # same location
        rec = mgr.checkin(
            s.session_id, student_id=2001, gps_location=GPSLocation(25.0331, 121.5655)
        )
        assert rec.status == CheckinStatus.PRESENT

    def test_gps_checkin_out_of_range(self, mgr: AttendanceManager):
        loc = GPSLocation(25.0330, 121.5654)
        s = mgr.create_session(
            "CS101", teacher_id=1001, gps_location=loc, gps_radius_m=100
        )
        # Far away
        with pytest.raises(ValueError, match="Too far"):
            mgr.checkin(
                s.session_id,
                student_id=2001,
                gps_location=GPSLocation(25.0500, 121.5654),
            )

    def test_gps_no_student_location_passes(self, mgr: AttendanceManager):
        """If session has GPS but student doesn't provide, allow (code-only mode)."""
        loc = GPSLocation(25.0330, 121.5654)
        s = mgr.create_session("CS101", teacher_id=1001, gps_location=loc)
        rec = mgr.checkin(s.session_id, student_id=2001)
        assert rec.status == CheckinStatus.PRESENT


# ------------------------------------------------------------------
# Stats
# ------------------------------------------------------------------


class TestStats:
    def test_empty_stats(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001)
        stats = mgr.session_stats(s.session_id)
        assert stats.total_checkins == 0
        assert stats.present_count == 0
        assert stats.late_count == 0

    def test_stats_with_checkins(self, mgr: AttendanceManager):
        s = mgr.create_session("CS101", teacher_id=1001, late_threshold_sec=0)
        # First student: will be late (threshold=0)
        mgr.checkin(s.session_id, student_id=2001)
        mgr.checkin(s.session_id, student_id=2002)
        stats = mgr.session_stats(s.session_id)
        assert stats.total_checkins == 2
        assert stats.late_count == 2
        assert 2001 in stats.student_ids
        assert 2002 in stats.student_ids

    def test_stats_nonexistent(self, mgr: AttendanceManager):
        with pytest.raises(KeyError):
            mgr.session_stats("nonexistent")


# ------------------------------------------------------------------
# Student history
# ------------------------------------------------------------------


class TestStudentHistory:
    def test_empty_history(self, mgr: AttendanceManager):
        assert mgr.student_history(2001) == []

    def test_history_across_sessions(self, mgr: AttendanceManager):
        s1 = mgr.create_session("CS101", teacher_id=1001, title="Week 1")
        s2 = mgr.create_session("CS101", teacher_id=1001, title="Week 2")
        mgr.checkin(s1.session_id, student_id=2001)
        mgr.checkin(s2.session_id, student_id=2001)
        history = mgr.student_history(2001)
        assert len(history) == 2
        assert history[0]["title"] == "Week 2"  # most recent first

    def test_history_filtered_by_course(self, mgr: AttendanceManager):
        s1 = mgr.create_session("CS101", teacher_id=1001)
        s2 = mgr.create_session("CS201", teacher_id=1001)
        mgr.checkin(s1.session_id, student_id=2001)
        mgr.checkin(s2.session_id, student_id=2001)
        history = mgr.student_history(2001, course_id="CS101")
        assert len(history) == 1


# ------------------------------------------------------------------
# API tests
# ------------------------------------------------------------------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from eduinsight.app import app

    with TestClient(app) as c:
        yield c


class TestAttendanceAPI:
    def _create_session(self, client, course_id="CS101") -> dict:
        resp = client.post(
            "/attendance/sessions",
            json={"course_id": course_id, "title": "Week 5"},
        )
        assert resp.status_code == 200
        return resp.json()

    def test_create_session(self, client):
        data = self._create_session(client)
        assert data["status"] == "open"
        assert len(data["checkin_code"]) == 6
        assert data["title"] == "Week 5"

    def test_create_with_gps(self, client):
        resp = client.post(
            "/attendance/sessions",
            json={
                "course_id": "CS101",
                "latitude": 25.033,
                "longitude": 121.565,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["has_gps"] is True

    def test_close_session(self, client):
        data = self._create_session(client)
        resp = client.post(f"/attendance/sessions/{data['session_id']}/close")
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"

    def test_close_not_found(self, client):
        resp = client.post("/attendance/sessions/nonexistent/close")
        assert resp.status_code == 404

    def test_get_session(self, client):
        data = self._create_session(client)
        resp = client.get(f"/attendance/sessions/{data['session_id']}")
        assert resp.status_code == 200
        assert resp.json()["session_id"] == data["session_id"]

    def test_list_sessions(self, client):
        self._create_session(client, "CS101")
        self._create_session(client, "CS201")
        resp = client.get("/attendance/sessions")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

        resp2 = client.get("/attendance/sessions?course_id=CS101")
        cs101 = [s for s in resp2.json() if s["course_id"] == "CS101"]
        assert len(cs101) >= 1

    def test_checkin(self, client):
        data = self._create_session(client)
        resp = client.post(
            f"/attendance/sessions/{data['session_id']}/checkin",
            json={"student_id": 2001},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "present"

    def test_checkin_with_code(self, client):
        data = self._create_session(client)
        resp = client.post(
            f"/attendance/sessions/{data['session_id']}/checkin",
            json={"student_id": 2001, "code": data["checkin_code"]},
        )
        assert resp.status_code == 200

    def test_checkin_wrong_code(self, client):
        data = self._create_session(client)
        resp = client.post(
            f"/attendance/sessions/{data['session_id']}/checkin",
            json={"student_id": 2001, "code": "WRONG1"},
        )
        assert resp.status_code == 400

    def test_get_records(self, client):
        data = self._create_session(client)
        client.post(
            f"/attendance/sessions/{data['session_id']}/checkin",
            json={"student_id": 2001},
        )
        client.post(
            f"/attendance/sessions/{data['session_id']}/checkin",
            json={"student_id": 2002},
        )
        resp = client.get(f"/attendance/sessions/{data['session_id']}/records")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_stats(self, client):
        data = self._create_session(client)
        client.post(
            f"/attendance/sessions/{data['session_id']}/checkin",
            json={"student_id": 2001},
        )
        resp = client.get(f"/attendance/sessions/{data['session_id']}/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_checkins"] == 1
        assert stats["present_count"] == 1

    def test_student_history(self, client):
        data = self._create_session(client)
        client.post(
            f"/attendance/sessions/{data['session_id']}/checkin",
            json={"student_id": 2001},
        )
        resp = client.get("/attendance/student/2001/history")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_checkin_by_code(self, client):
        data = self._create_session(client)
        resp = client.post(
            "/attendance/checkin-by-code",
            json={"student_id": 2001, "code": data["checkin_code"]},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "present"

    def test_checkin_by_code_not_found(self, client):
        resp = client.post(
            "/attendance/checkin-by-code",
            json={"student_id": 2001, "code": "ZZZZZZ"},
        )
        assert resp.status_code == 404

    def test_checkin_by_code_no_code(self, client):
        resp = client.post(
            "/attendance/checkin-by-code",
            json={"student_id": 2001},
        )
        assert resp.status_code == 400
