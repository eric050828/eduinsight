"""Demo grade data for the 5 demo students across ds101 course."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .grades import GradeManager

# ds101 資料結構 — grade categories
DS101_CATEGORIES = [
    {"name": "作業", "weight": 30},
    {"name": "期中考", "weight": 30},
    {"name": "期末考", "weight": 40},
]

# (student_id, category, item, score, total)
DS101_SCORES: list[tuple[int, str, str, float, float]] = [
    # 1001 A 陳同學 — mid-level, struggles with trees
    (1001, "作業", "HW1", 82, 100),
    (1001, "作業", "HW2", 75, 100),
    (1001, "作業", "HW3", 70, 100),
    (1001, "期中考", "期中考", 68, 100),
    # 1002 B 林同學 — advanced, strong algorithm skills
    (1002, "作業", "HW1", 95, 100),
    (1002, "作業", "HW2", 92, 100),
    (1002, "作業", "HW3", 98, 100),
    (1002, "期中考", "期中考", 91, 100),
    # 1003 C 王同學 — retake, struggling
    (1003, "作業", "HW1", 55, 100),
    (1003, "作業", "HW2", 48, 100),
    (1003, "作業", "HW3", 40, 100),
    (1003, "期中考", "期中考", 45, 100),
    # 1004 D 李同學 — at-risk, minimal engagement
    (1004, "作業", "HW1", 60, 100),
    (1004, "作業", "HW2", 35, 100),
    (1004, "作業", "HW3", 28, 100),
    (1004, "期中考", "期中考", 23, 100),
    # 1005 E 張同學 — mid-level, DB focus
    (1005, "作業", "HW1", 78, 100),
    (1005, "作業", "HW2", 80, 100),
    (1005, "作業", "HW3", 73, 100),
    (1005, "期中考", "期中考", 72, 100),
]


def seed_demo_grades(mgr: GradeManager) -> None:
    """Seed demo grade data into the GradeManager.

    Clears existing ds101 data and seeds fresh categories + scores.
    """
    # Reset by re-setting categories (clears internal state for course)
    mgr.set_categories("ds101", DS101_CATEGORIES)
    # Clear any existing scores for ds101
    mgr._scores["ds101"] = []

    for student_id, category, item, score, total in DS101_SCORES:
        mgr.record_score(
            "ds101",
            student_id=student_id,
            category=category,
            item=item,
            score=score,
            total=total,
        )
