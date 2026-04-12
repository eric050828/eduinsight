"""Grade management with weighted scoring, distribution analysis, and rankings.

Supports configurable grade categories with adjustable weights.
Teachers define categories (homework, quiz, midterm, etc.) per course,
then record scores for each student. The system computes weighted totals
in real-time.

Usage::

    mgr = GradeManager()

    # Teacher sets up categories for a course
    mgr.set_categories("CS101", [
        {"name": "作業", "weight": 30},
        {"name": "期中考", "weight": 30},
        {"name": "期末考", "weight": 40},
    ])

    # Record scores
    mgr.record_score("CS101", student_id=2001, category="作業", item="HW1", score=85, total=100)

    # Get weighted total
    summary = mgr.student_summary("CS101", student_id=2001)
    # summary.weighted_total → 85 * 0.3 = 25.5 (only 作業 has scores so far)

    # Class overview
    overview = mgr.class_overview("CS101")
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class GradeCategory:
    """A grade category (e.g. homework, midterm) with a weight."""

    name: str
    weight: float  # percentage, e.g. 30 = 30%


@dataclass
class ScoreRecord:
    """A single score entry for a student in a category."""

    record_id: str
    course_id: str
    student_id: int
    category: str
    item: str  # e.g. "HW1", "Midterm"
    score: float
    total: float  # max possible score for this item
    created_at: float = 0.0


@dataclass
class CategorySummary:
    """Summary of a student's scores within one category."""

    category: str
    weight: float
    items: list[dict[str, Any]]  # [{item, score, total}, ...]
    average_pct: float  # average percentage across items
    weighted_contribution: float  # average_pct * weight / 100


@dataclass
class StudentGradeSummary:
    """Full grade summary for one student in a course."""

    course_id: str
    student_id: int
    categories: list[CategorySummary]
    weighted_total: float  # sum of all weighted contributions
    rank: int | None = None  # class rank (1-based)
    total_students: int | None = None


@dataclass
class ClassOverview:
    """Class-level grade statistics."""

    course_id: str
    total_students: int
    mean: float
    median: float
    std_dev: float
    min_score: float
    max_score: float
    distribution: dict[str, int]  # grade band → count (A/B/C/D/F)
    rankings: list[dict[str, Any]]  # [{student_id, weighted_total, rank}, ...]


class GradeManager:
    """In-memory manager for course grades.

    Thread-safety note: single-process demo store.
    """

    def __init__(self) -> None:
        # course_id → list of GradeCategory
        self._categories: dict[str, list[GradeCategory]] = {}
        # course_id → list of ScoreRecord
        self._scores: dict[str, list[ScoreRecord]] = {}

    # ── Category configuration ───────────────────────────────────

    def set_categories(
        self, course_id: str, categories: list[dict[str, Any]]
    ) -> list[GradeCategory]:
        """Set grade categories and weights for a course.

        Args:
            course_id: Course identifier.
            categories: List of {"name": str, "weight": float} dicts.
                Weights should sum to 100.

        Raises:
            ValueError: If categories are empty or weights are invalid.
        """
        if not categories:
            raise ValueError("At least one category is required")

        parsed: list[GradeCategory] = []
        for cat in categories:
            name = cat.get("name", "").strip()
            weight = cat.get("weight", 0)
            if not name:
                raise ValueError("Category name cannot be empty")
            if weight <= 0:
                raise ValueError(f"Weight for '{name}' must be positive")
            parsed.append(GradeCategory(name=name, weight=float(weight)))

        total_weight = sum(c.weight for c in parsed)
        if abs(total_weight - 100) > 0.01:
            raise ValueError(
                f"Weights must sum to 100, got {total_weight:.1f}"
            )

        self._categories[course_id] = parsed
        # Initialize scores list if not exists
        if course_id not in self._scores:
            self._scores[course_id] = []
        return parsed

    def get_categories(self, course_id: str) -> list[GradeCategory]:
        """Get grade categories for a course.

        Raises:
            KeyError: If course has no categories configured.
        """
        if course_id not in self._categories:
            raise KeyError(f"No grade categories configured for course '{course_id}'")
        return list(self._categories[course_id])

    # ── Score recording ──────────────────────────────────────────

    def record_score(
        self,
        course_id: str,
        *,
        student_id: int,
        category: str,
        item: str,
        score: float,
        total: float = 100.0,
    ) -> ScoreRecord:
        """Record a score for a student.

        Args:
            course_id: Course identifier.
            student_id: Student identifier.
            category: Category name (must match a configured category).
            item: Item name (e.g. "HW1", "Midterm").
            score: Achieved score.
            total: Maximum possible score (default 100).

        Raises:
            KeyError: If course has no categories.
            ValueError: If category not found, score invalid, or duplicate item.
        """
        cats = self.get_categories(course_id)
        cat_names = [c.name for c in cats]
        if category not in cat_names:
            raise ValueError(
                f"Category '{category}' not found. Available: {cat_names}"
            )
        if total <= 0:
            raise ValueError("Total must be positive")
        if score < 0:
            raise ValueError("Score cannot be negative")
        if score > total:
            raise ValueError(f"Score ({score}) exceeds total ({total})")

        # Check for duplicate item
        for rec in self._scores.get(course_id, []):
            if (
                rec.student_id == student_id
                and rec.category == category
                and rec.item == item
            ):
                # Update existing score
                rec.score = score
                rec.total = total
                return rec

        import time

        record = ScoreRecord(
            record_id=f"score_{uuid.uuid4().hex[:12]}",
            course_id=course_id,
            student_id=student_id,
            category=category,
            item=item,
            score=score,
            total=total,
            created_at=time.time(),
        )
        self._scores[course_id].append(record)
        return record

    def delete_score(
        self, course_id: str, *, student_id: int, category: str, item: str
    ) -> bool:
        """Delete a specific score record.

        Returns True if found and deleted, False otherwise.
        """
        records = self._scores.get(course_id, [])
        for i, rec in enumerate(records):
            if (
                rec.student_id == student_id
                and rec.category == category
                and rec.item == item
            ):
                records.pop(i)
                return True
        return False

    def get_scores(
        self,
        course_id: str,
        student_id: int | None = None,
        category: str | None = None,
    ) -> list[ScoreRecord]:
        """Get score records, optionally filtered by student and/or category."""
        records = self._scores.get(course_id, [])
        if student_id is not None:
            records = [r for r in records if r.student_id == student_id]
        if category is not None:
            records = [r for r in records if r.category == category]
        return records

    # ── Student summary ──────────────────────────────────────────

    def student_summary(
        self, course_id: str, student_id: int
    ) -> StudentGradeSummary:
        """Compute weighted grade summary for one student.

        Raises:
            KeyError: If course has no categories.
        """
        cats = self.get_categories(course_id)
        scores = self.get_scores(course_id, student_id=student_id)

        cat_summaries: list[CategorySummary] = []
        weighted_total = 0.0

        for cat in cats:
            cat_scores = [s for s in scores if s.category == cat.name]
            items = [
                {"item": s.item, "score": s.score, "total": s.total}
                for s in cat_scores
            ]
            if cat_scores:
                pcts = [s.score / s.total * 100 for s in cat_scores]
                avg_pct = sum(pcts) / len(pcts)
            else:
                avg_pct = 0.0

            contribution = avg_pct * cat.weight / 100
            weighted_total += contribution

            cat_summaries.append(
                CategorySummary(
                    category=cat.name,
                    weight=cat.weight,
                    items=items,
                    average_pct=round(avg_pct, 2),
                    weighted_contribution=round(contribution, 2),
                )
            )

        return StudentGradeSummary(
            course_id=course_id,
            student_id=student_id,
            categories=cat_summaries,
            weighted_total=round(weighted_total, 2),
        )

    # ── Class overview ───────────────────────────────────────────

    def _all_student_ids(self, course_id: str) -> set[int]:
        """Get all student IDs that have any score in this course."""
        return {r.student_id for r in self._scores.get(course_id, [])}

    def class_overview(self, course_id: str) -> ClassOverview:
        """Compute class-level grade statistics and rankings.

        Raises:
            KeyError: If course has no categories.
        """
        self.get_categories(course_id)  # validate course exists
        student_ids = self._all_student_ids(course_id)

        if not student_ids:
            return ClassOverview(
                course_id=course_id,
                total_students=0,
                mean=0.0,
                median=0.0,
                std_dev=0.0,
                min_score=0.0,
                max_score=0.0,
                distribution={"A": 0, "B": 0, "C": 0, "D": 0, "F": 0},
                rankings=[],
            )

        # Compute weighted total for each student
        totals: list[tuple[int, float]] = []
        for sid in student_ids:
            summary = self.student_summary(course_id, sid)
            totals.append((sid, summary.weighted_total))

        # Sort by score descending
        totals.sort(key=lambda x: x[1], reverse=True)

        # Rankings with proper tie handling
        rankings: list[dict[str, Any]] = []
        prev_score: float | None = None
        prev_rank = 0
        for i, (sid, wt) in enumerate(totals):
            if wt != prev_score:
                rank = i + 1
            else:
                rank = prev_rank
            rankings.append(
                {"student_id": sid, "weighted_total": round(wt, 2), "rank": rank}
            )
            prev_score = wt
            prev_rank = rank

        scores_list = [wt for _, wt in totals]

        # Distribution bands (percentage-based)
        dist = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        for sc in scores_list:
            if sc >= 90:
                dist["A"] += 1
            elif sc >= 80:
                dist["B"] += 1
            elif sc >= 70:
                dist["C"] += 1
            elif sc >= 60:
                dist["D"] += 1
            else:
                dist["F"] += 1

        std = statistics.stdev(scores_list) if len(scores_list) > 1 else 0.0

        return ClassOverview(
            course_id=course_id,
            total_students=len(student_ids),
            mean=round(statistics.mean(scores_list), 2),
            median=round(statistics.median(scores_list), 2),
            std_dev=round(std, 2),
            min_score=round(min(scores_list), 2),
            max_score=round(max(scores_list), 2),
            distribution=dist,
            rankings=rankings,
        )

    def student_summary_with_rank(
        self, course_id: str, student_id: int
    ) -> StudentGradeSummary:
        """Like student_summary but also populates rank and total_students."""
        overview = self.class_overview(course_id)
        summary = self.student_summary(course_id, student_id)
        summary.total_students = overview.total_students
        for entry in overview.rankings:
            if entry["student_id"] == student_id:
                summary.rank = entry["rank"]
                break
        return summary

    def list_courses(self) -> list[str]:
        """List all courses that have categories configured."""
        return list(self._categories.keys())
