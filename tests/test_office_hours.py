"""Tests for Office Hour booking and AI learning summary system."""

from __future__ import annotations

import time

import pytest
from litemem import Memory

from eduinsight.office_hours import (
    BookingStatus,
    OfficeHourManager,
    SlotStatus,
    StudentSummary,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _ts(offset_hours: float = 0) -> float:
    """Current time + offset in hours."""
    return time.time() + offset_hours * 3600


@pytest.fixture
def mem():
    return Memory(":memory:")


@pytest.fixture
def mgr(mem):
    return OfficeHourManager(memory=mem)


# ── Slot operations ──────────────────────────────────────────────────


class TestSlotOperations:
    def test_create_slot(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        assert slot.slot_id.startswith("slot_")
        assert slot.status == SlotStatus.AVAILABLE
        assert slot.course_id == "CS101"

    def test_create_slot_with_location(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
            location="Room 301",
        )
        assert slot.location == "Room 301"

    def test_create_slot_invalid_time(self, mgr):
        with pytest.raises(ValueError, match="end_time must be after"):
            mgr.create_slot(
                "CS101", teacher_id=1,
                start_time=_ts(2), end_time=_ts(1),
            )

    def test_list_slots_empty(self, mgr):
        assert mgr.list_slots("CS101") == []

    def test_list_slots_filtered(self, mgr):
        mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        mgr.create_slot(
            "CS102", teacher_id=1,
            start_time=_ts(3), end_time=_ts(4),
        )
        assert len(mgr.list_slots("CS101")) == 1
        assert len(mgr.list_slots()) == 2

    def test_list_slots_by_status(self, mgr):
        s1 = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(3), end_time=_ts(4),
        )
        mgr.cancel_slot(s1.slot_id)
        available = mgr.list_slots("CS101", status=SlotStatus.AVAILABLE)
        assert len(available) == 1

    def test_get_slot(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        assert mgr.get_slot(slot.slot_id).slot_id == slot.slot_id

    def test_get_slot_not_found(self, mgr):
        with pytest.raises(KeyError):
            mgr.get_slot("nonexistent")

    def test_cancel_slot(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        cancelled = mgr.cancel_slot(slot.slot_id)
        assert cancelled.status == SlotStatus.CANCELLED

    def test_cancel_booked_slot_fails(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        mgr.book_slot(slot.slot_id, student_id=2001)
        with pytest.raises(ValueError, match="Cannot cancel"):
            mgr.cancel_slot(slot.slot_id)

    def test_slots_sorted_by_time(self, mgr):
        mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(3), end_time=_ts(4),
        )
        mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        slots = mgr.list_slots("CS101")
        assert slots[0].start_time < slots[1].start_time


# ── Booking operations ───────────────────────────────────────────────


class TestBookingOperations:
    def test_book_slot(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        booking = mgr.book_slot(
            slot.slot_id, student_id=2001, topic="DP 不太懂",
        )
        assert booking.booking_id.startswith("bk_")
        assert booking.status == BookingStatus.PENDING
        assert booking.student_id == 2001
        assert booking.topic == "DP 不太懂"
        assert slot.status == SlotStatus.BOOKED

    def test_book_unavailable_slot(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        mgr.book_slot(slot.slot_id, student_id=2001)
        with pytest.raises(ValueError, match="not available"):
            mgr.book_slot(slot.slot_id, student_id=2002)

    def test_get_booking(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        bk = mgr.book_slot(slot.slot_id, student_id=2001)
        assert mgr.get_booking(bk.booking_id).student_id == 2001

    def test_get_booking_not_found(self, mgr):
        with pytest.raises(KeyError):
            mgr.get_booking("nonexistent")

    def test_list_bookings_by_student(self, mgr):
        s1 = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        s2 = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(3), end_time=_ts(4),
        )
        mgr.book_slot(s1.slot_id, student_id=2001)
        mgr.book_slot(s2.slot_id, student_id=2002)
        assert len(mgr.list_bookings(student_id=2001)) == 1

    def test_list_bookings_by_course(self, mgr):
        s1 = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        s2 = mgr.create_slot(
            "CS102", teacher_id=1,
            start_time=_ts(3), end_time=_ts(4),
        )
        mgr.book_slot(s1.slot_id, student_id=2001)
        mgr.book_slot(s2.slot_id, student_id=2001)
        assert len(mgr.list_bookings(course_id="CS101")) == 1

    def test_list_bookings_by_status(self, mgr):
        s1 = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        s2 = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(3), end_time=_ts(4),
        )
        bk1 = mgr.book_slot(s1.slot_id, student_id=2001)
        mgr.book_slot(s2.slot_id, student_id=2002)
        mgr.start_meeting(bk1.booking_id)
        mgr.resolve_booking(bk1.booking_id, notes="Done")
        pending = mgr.list_bookings(status=BookingStatus.PENDING)
        assert len(pending) == 1


# ── Meeting lifecycle ────────────────────────────────────────────────


class TestMeetingLifecycle:
    def test_start_meeting(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        bk = mgr.book_slot(slot.slot_id, student_id=2001)
        meeting = mgr.start_meeting(bk.booking_id)
        assert meeting.status == BookingStatus.IN_PROGRESS

    def test_start_non_pending_fails(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        bk = mgr.book_slot(slot.slot_id, student_id=2001)
        mgr.start_meeting(bk.booking_id)
        with pytest.raises(ValueError, match="not pending"):
            mgr.start_meeting(bk.booking_id)

    def test_resolve_booking(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        bk = mgr.book_slot(slot.slot_id, student_id=2001)
        mgr.start_meeting(bk.booking_id)
        resolved = mgr.resolve_booking(
            bk.booking_id, notes="已解釋 DP 表格法",
        )
        assert resolved.status == BookingStatus.COMPLETED
        assert resolved.resolution_notes == "已解釋 DP 表格法"
        assert resolved.completed_at > 0
        assert slot.status == SlotStatus.COMPLETED

    def test_resolve_records_to_memory(self, mgr, mem):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        bk = mgr.book_slot(slot.slot_id, student_id=2001)
        mgr.resolve_booking(bk.booking_id, notes="解釋了 recursion")

        facts = mem.list("moodle:2001")
        assert any("Office Hour" in f and "recursion" in f for f in facts)

    def test_resolve_without_notes_no_memory(self, mgr, mem):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        bk = mgr.book_slot(slot.slot_id, student_id=2001)
        mgr.resolve_booking(bk.booking_id)  # no notes

        facts = mem.list("moodle:2001")
        assert len(facts) == 0

    def test_resolve_completed_fails(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        bk = mgr.book_slot(slot.slot_id, student_id=2001)
        mgr.resolve_booking(bk.booking_id, notes="Done")
        with pytest.raises(ValueError, match="cannot resolve"):
            mgr.resolve_booking(bk.booking_id, notes="Again")

    def test_cancel_booking(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        bk = mgr.book_slot(slot.slot_id, student_id=2001)
        cancelled = mgr.cancel_booking(bk.booking_id)
        assert cancelled.status == BookingStatus.CANCELLED
        assert slot.status == SlotStatus.AVAILABLE  # slot freed

    def test_cancel_completed_fails(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        bk = mgr.book_slot(slot.slot_id, student_id=2001)
        mgr.resolve_booking(bk.booking_id, notes="Done")
        with pytest.raises(ValueError, match="Cannot cancel"):
            mgr.cancel_booking(bk.booking_id)

    def test_mark_no_show(self, mgr):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        bk = mgr.book_slot(slot.slot_id, student_id=2001)
        no_show = mgr.mark_no_show(bk.booking_id)
        assert no_show.status == BookingStatus.NO_SHOW
        assert slot.status == SlotStatus.COMPLETED


# ── Student summary ──────────────────────────────────────────────────


class TestStudentSummary:
    def test_summary_empty_student(self, mgr, mem):
        summary = mgr.get_student_summary(9999)
        assert summary.total_facts == 0
        assert summary.struggles == []

    def test_summary_with_facts(self, mgr, mem):
        uid = "moodle:2001"
        mem.add(uid, "Struggling with: recursion", category="struggling")
        mem.add(uid, "[Trees] Binary tree traversal", category="general")
        mem.add(
            uid, "Learning preference: visual diagrams",
            category="preference",
        )

        summary = mgr.get_student_summary(2001)
        assert summary.total_facts == 3
        assert len(summary.struggles) == 1
        assert "recursion" in summary.struggles[0]
        assert "Trees" in summary.weak_topics
        assert len(summary.preferences) == 1
        assert "學習摘要" in summary.summary_text

    def test_summary_includes_booking_topics(self, mgr, mem):
        slot = mgr.create_slot(
            "CS101", teacher_id=1,
            start_time=_ts(1), end_time=_ts(2),
        )
        mgr.book_slot(
            slot.slot_id, student_id=2001, topic="DP 不太懂",
        )

        summary = mgr.get_student_summary(2001)
        assert "DP 不太懂" in summary.recent_questions

    def test_summary_without_memory(self):
        mgr = OfficeHourManager()  # no memory
        summary = mgr.get_student_summary(2001)
        assert summary.total_facts == 0
        assert isinstance(summary, StudentSummary)

    def test_summary_text_format(self, mgr, mem):
        uid = "moodle:2001"
        mem.add(uid, "Struggling with DP: 表格法不理解", category="struggling")
        mem.add(uid, "Struggling with graphs: DFS 搞不清", category="struggling")

        summary = mgr.get_student_summary(2001)
        assert "困難項目" in summary.summary_text
        assert "2 項" in summary.summary_text


# ── API endpoint tests ───────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from eduinsight.app import app

    with TestClient(app) as c:
        yield c


class TestOfficeHourAPI:
    def test_create_slot(self, client):
        resp = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "teacher_id": 1,
            "start_time": _ts(1),
            "end_time": _ts(2),
            "location": "Room 301",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["slot_id"].startswith("slot_")
        assert data["status"] == "available"
        assert data["location"] == "Room 301"

    def test_create_slot_invalid_time(self, client):
        resp = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(2),
            "end_time": _ts(1),
        })
        assert resp.status_code == 400

    def test_list_slots(self, client):
        client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        resp = client.get("/office-hours/slots", params={"course_id": "CS101"})
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_slot(self, client):
        create = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        slot_id = create.json()["slot_id"]
        resp = client.get(f"/office-hours/slots/{slot_id}")
        assert resp.status_code == 200
        assert resp.json()["slot_id"] == slot_id

    def test_get_slot_not_found(self, client):
        resp = client.get("/office-hours/slots/nonexistent")
        assert resp.status_code == 404

    def test_cancel_slot(self, client):
        create = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        slot_id = create.json()["slot_id"]
        resp = client.post(f"/office-hours/slots/{slot_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_book_slot(self, client):
        create = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        slot_id = create.json()["slot_id"]
        resp = client.post(f"/office-hours/slots/{slot_id}/book", json={
            "student_id": 2001,
            "topic": "DP 不太懂",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["booking_id"].startswith("bk_")
        assert data["student_id"] == 2001
        assert data["topic"] == "DP 不太懂"
        assert data["status"] == "pending"

    def test_book_unavailable_slot(self, client):
        create = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        slot_id = create.json()["slot_id"]
        client.post(f"/office-hours/slots/{slot_id}/book", json={
            "student_id": 2001,
        })
        resp = client.post(f"/office-hours/slots/{slot_id}/book", json={
            "student_id": 2002,
        })
        assert resp.status_code == 400

    def test_list_bookings(self, client):
        create = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        slot_id = create.json()["slot_id"]
        client.post(f"/office-hours/slots/{slot_id}/book", json={
            "student_id": 2001,
        })
        resp = client.get("/office-hours/bookings", params={"student_id": 2001})
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_booking(self, client):
        create = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        slot_id = create.json()["slot_id"]
        book = client.post(f"/office-hours/slots/{slot_id}/book", json={
            "student_id": 2001,
        })
        booking_id = book.json()["booking_id"]
        resp = client.get(f"/office-hours/bookings/{booking_id}")
        assert resp.status_code == 200
        assert resp.json()["student_id"] == 2001

    def test_start_meeting(self, client):
        create = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        slot_id = create.json()["slot_id"]
        book = client.post(f"/office-hours/slots/{slot_id}/book", json={
            "student_id": 2001,
        })
        booking_id = book.json()["booking_id"]
        resp = client.post(f"/office-hours/bookings/{booking_id}/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    def test_resolve_booking(self, client):
        create = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        slot_id = create.json()["slot_id"]
        book = client.post(f"/office-hours/slots/{slot_id}/book", json={
            "student_id": 2001,
        })
        booking_id = book.json()["booking_id"]
        resp = client.post(f"/office-hours/bookings/{booking_id}/resolve", json={
            "notes": "已解釋 DP 表格法",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
        assert resp.json()["resolution_notes"] == "已解釋 DP 表格法"

    def test_cancel_booking(self, client):
        create = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        slot_id = create.json()["slot_id"]
        book = client.post(f"/office-hours/slots/{slot_id}/book", json={
            "student_id": 2001,
        })
        booking_id = book.json()["booking_id"]
        resp = client.post(f"/office-hours/bookings/{booking_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_mark_no_show(self, client):
        create = client.post("/office-hours/slots", json={
            "course_id": "CS101",
            "start_time": _ts(1),
            "end_time": _ts(2),
        })
        slot_id = create.json()["slot_id"]
        book = client.post(f"/office-hours/slots/{slot_id}/book", json={
            "student_id": 2001,
        })
        booking_id = book.json()["booking_id"]
        resp = client.post(f"/office-hours/bookings/{booking_id}/no-show")
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_show"

    def test_student_summary(self, client):
        resp = client.get("/office-hours/students/9999/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["student_id"] == 9999
        assert "total_facts" in data
        assert "summary_text" in data
