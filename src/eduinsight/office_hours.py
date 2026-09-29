"""Office Hour management — booking, AI learning summaries, and follow-up.

Supports the office hour workflow:
1. Teacher creates available time slots
2. Student books a slot (with optional topic description)
3. Before meeting: AI generates a learning summary for the teacher
4. After meeting: teacher records resolution notes → updates student memory

Usage::

    manager = OfficeHourManager(memory=Memory(":memory:"))
    slot = manager.create_slot("CS101", teacher_id=1, start=..., end=...)
    booking = manager.book_slot(slot.slot_id, student_id=2001, topic="DP 不太懂")
    summary = manager.get_student_summary(2001, memory)
    manager.resolve_booking(booking.booking_id, notes="已解釋 DP 表格法")
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from litemem import Memory


class SlotStatus(StrEnum):
    AVAILABLE = "available"
    BOOKED = "booked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BookingStatus(StrEnum):
    PENDING = "pending"  # booked, not yet met
    IN_PROGRESS = "in_progress"  # meeting ongoing
    COMPLETED = "completed"  # meeting done, notes recorded
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


@dataclass
class TimeSlot:
    """An available office hour time slot."""

    slot_id: str
    course_id: str
    teacher_id: int
    start_time: float  # unix timestamp
    end_time: float
    location: str = ""  # room, Zoom link, etc.
    status: SlotStatus = SlotStatus.AVAILABLE
    created_at: float = field(default_factory=time.time)


@dataclass
class Booking:
    """A student's office hour booking."""

    booking_id: str
    slot_id: str
    course_id: str
    student_id: int
    teacher_id: int
    topic: str = ""  # what the student wants to discuss
    status: BookingStatus = BookingStatus.PENDING
    resolution_notes: str = ""  # teacher's post-meeting notes
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0


@dataclass
class StudentSummary:
    """AI-generated learning summary for a student."""

    student_id: int
    total_facts: int = 0
    struggles: list[str] = field(default_factory=list)
    weak_topics: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    recent_questions: list[str] = field(default_factory=list)
    risk_level: str = ""
    summary_text: str = ""


class OfficeHourManager:
    """Manages office hour slots and bookings (in-memory store).

    Thread-safety note: single-process demo store.
    """

    def __init__(self, memory: Memory | None = None) -> None:
        self._slots: dict[str, TimeSlot] = {}
        self._bookings: dict[str, Booking] = {}
        self._memory = memory

    # ── Slot operations ──────────────────────────────────────────

    def create_slot(
        self,
        course_id: str,
        *,
        teacher_id: int,
        start_time: float,
        end_time: float,
        location: str = "",
    ) -> TimeSlot:
        """Create an available office hour slot.

        Raises:
            ValueError: If end_time <= start_time.
        """
        if end_time <= start_time:
            raise ValueError("end_time must be after start_time")

        slot_id = f"slot_{uuid.uuid4().hex[:12]}"
        slot = TimeSlot(
            slot_id=slot_id,
            course_id=course_id,
            teacher_id=teacher_id,
            start_time=start_time,
            end_time=end_time,
            location=location,
        )
        self._slots[slot_id] = slot
        return slot

    def list_slots(
        self,
        course_id: str | None = None,
        *,
        status: SlotStatus | None = None,
    ) -> list[TimeSlot]:
        """List slots, optionally filtered."""
        slots = list(self._slots.values())
        if course_id:
            slots = [s for s in slots if s.course_id == course_id]
        if status:
            slots = [s for s in slots if s.status == status]
        return sorted(slots, key=lambda s: s.start_time)

    def get_slot(self, slot_id: str) -> TimeSlot:
        """Get slot by ID.

        Raises:
            KeyError: If slot not found.
        """
        if slot_id not in self._slots:
            raise KeyError(f"Slot '{slot_id}' not found")
        return self._slots[slot_id]

    def cancel_slot(self, slot_id: str) -> TimeSlot:
        """Cancel an available slot.

        Raises:
            KeyError: If slot not found.
            ValueError: If slot is not available.
        """
        slot = self.get_slot(slot_id)
        if slot.status != SlotStatus.AVAILABLE:
            raise ValueError(
                f"Cannot cancel slot in '{slot.status}' status"
            )
        slot.status = SlotStatus.CANCELLED
        return slot

    # ── Booking operations ───────────────────────────────────────

    def book_slot(
        self,
        slot_id: str,
        *,
        student_id: int,
        topic: str = "",
    ) -> Booking:
        """Book an available slot for a student.

        Raises:
            KeyError: If slot not found.
            ValueError: If slot is not available.
        """
        slot = self.get_slot(slot_id)
        if slot.status != SlotStatus.AVAILABLE:
            raise ValueError(
                f"Slot is '{slot.status}', not available for booking"
            )

        booking_id = f"bk_{uuid.uuid4().hex[:12]}"
        booking = Booking(
            booking_id=booking_id,
            slot_id=slot_id,
            course_id=slot.course_id,
            student_id=student_id,
            teacher_id=slot.teacher_id,
            topic=topic,
        )
        self._bookings[booking_id] = booking
        slot.status = SlotStatus.BOOKED
        return booking

    def get_booking(self, booking_id: str) -> Booking:
        """Get booking by ID.

        Raises:
            KeyError: If booking not found.
        """
        if booking_id not in self._bookings:
            raise KeyError(f"Booking '{booking_id}' not found")
        return self._bookings[booking_id]

    def list_bookings(
        self,
        *,
        course_id: str | None = None,
        student_id: int | None = None,
        teacher_id: int | None = None,
        status: BookingStatus | None = None,
    ) -> list[Booking]:
        """List bookings with optional filters."""
        bookings = list(self._bookings.values())
        if course_id:
            bookings = [b for b in bookings if b.course_id == course_id]
        if student_id is not None:
            bookings = [
                b for b in bookings if b.student_id == student_id
            ]
        if teacher_id is not None:
            bookings = [
                b for b in bookings if b.teacher_id == teacher_id
            ]
        if status:
            bookings = [b for b in bookings if b.status == status]
        return sorted(bookings, key=lambda b: b.created_at, reverse=True)

    def start_meeting(self, booking_id: str) -> Booking:
        """Mark a booking as in-progress (meeting started).

        Raises:
            KeyError: If booking not found.
            ValueError: If booking not in pending status.
        """
        booking = self.get_booking(booking_id)
        if booking.status != BookingStatus.PENDING:
            raise ValueError(
                f"Booking is '{booking.status}', not pending"
            )
        booking.status = BookingStatus.IN_PROGRESS
        return booking

    def resolve_booking(
        self,
        booking_id: str,
        *,
        notes: str = "",
    ) -> Booking:
        """Complete a booking with resolution notes.

        Marks the booking as completed and optionally records notes
        to the student's memory via Lite-Mem.

        Raises:
            KeyError: If booking not found.
            ValueError: If booking already completed/cancelled.
        """
        booking = self.get_booking(booking_id)
        if booking.status in (
            BookingStatus.COMPLETED,
            BookingStatus.CANCELLED,
        ):
            raise ValueError(
                f"Booking is '{booking.status}', cannot resolve"
            )

        booking.status = BookingStatus.COMPLETED
        booking.resolution_notes = notes
        booking.completed_at = time.time()

        # Update slot status
        slot = self.get_slot(booking.slot_id)
        slot.status = SlotStatus.COMPLETED

        # Record resolution to student memory
        if notes and self._memory:
            uid = f"moodle:{booking.student_id}"
            fact = f"[Office Hour] 已當面解決：{notes}"
            self._memory.add(uid, fact, category="general", extract=False)

        return booking

    def cancel_booking(self, booking_id: str) -> Booking:
        """Cancel a booking, returning the slot to available.

        Raises:
            KeyError: If booking not found.
            ValueError: If booking already completed.
        """
        booking = self.get_booking(booking_id)
        if booking.status == BookingStatus.COMPLETED:
            raise ValueError("Cannot cancel a completed booking")

        booking.status = BookingStatus.CANCELLED

        # Return slot to available
        slot = self.get_slot(booking.slot_id)
        slot.status = SlotStatus.AVAILABLE
        return booking

    def mark_no_show(self, booking_id: str) -> Booking:
        """Mark a student as no-show.

        Raises:
            KeyError: If booking not found.
        """
        booking = self.get_booking(booking_id)
        booking.status = BookingStatus.NO_SHOW
        slot = self.get_slot(booking.slot_id)
        slot.status = SlotStatus.COMPLETED
        return booking

    # ── Student summary ──────────────────────────────────────────

    def get_student_summary(
        self,
        student_id: int,
        memory: Memory | None = None,
    ) -> StudentSummary:
        """Generate a learning summary for a student.

        Pulls data from Lite-Mem to create a pre-meeting brief.

        Args:
            student_id: Moodle student ID.
            memory: Memory instance (uses self._memory if not provided).

        Returns:
            StudentSummary with struggles, preferences, and risk info.
        """
        mem = memory or self._memory
        uid = f"moodle:{student_id}"
        summary = StudentSummary(student_id=student_id)

        if not mem:
            return summary

        # Get all facts for this student
        facts = mem.list(uid)
        summary.total_facts = len(facts)

        for fact in facts:
            text = str(fact)
            lower = text.lower()

            if "struggling" in lower or "困難" in lower:
                summary.struggles.append(text)
            elif "preference" in lower or "偏好" in lower:
                summary.preferences.append(text)

            # Extract topics from [Topic] prefix
            if text.startswith("["):
                bracket_end = text.find("]")
                if bracket_end > 0:
                    topic = text[1:bracket_end]
                    if topic not in summary.weak_topics:
                        summary.weak_topics.append(topic)

        # Get recent questions from bookings
        student_bookings = self.list_bookings(student_id=student_id)
        for bk in student_bookings[:5]:
            if bk.topic:
                summary.recent_questions.append(bk.topic)

        # Build summary text
        parts = [f"學生 {student_id} 學習摘要："]
        parts.append(f"累計 {summary.total_facts} 筆學習記錄")
        if summary.struggles:
            parts.append(
                f"困難項目 ({len(summary.struggles)} 項)："
                + "、".join(s[:30] for s in summary.struggles[:5])
            )
        if summary.weak_topics:
            parts.append(
                "涉及主題：" + "、".join(summary.weak_topics[:8])
            )
        if summary.preferences:
            parts.append(
                "學習偏好：" + "、".join(
                    p[:30] for p in summary.preferences[:3]
                )
            )
        summary.summary_text = "\n".join(parts)

        return summary
