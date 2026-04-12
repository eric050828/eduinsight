"""Demo grade data for the 5 demo students across ds101, py101, db101 courses."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .grades import GradeManager

# ── ds101 資料結構 ──
DS101_CATEGORIES = [
    {"name": "作業", "weight": 30},
    {"name": "期中考", "weight": 30},
    {"name": "期末考", "weight": 40},
]

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

# ── py101 Python 程式設計 ──
PY101_CATEGORIES = [
    {"name": "Lab", "weight": 40},
    {"name": "期中考", "weight": 25},
    {"name": "期末專題", "weight": 35},
]

PY101_SCORES: list[tuple[int, str, str, float, float]] = [
    # 1001 A 陳同學 — decent at Python
    (1001, "Lab", "Lab1", 88, 100),
    (1001, "Lab", "Lab2", 85, 100),
    (1001, "Lab", "Lab3", 80, 100),
    (1001, "期中考", "期中考", 78, 100),
    # 1003 C 王同學 — struggles with programming
    (1003, "Lab", "Lab1", 50, 100),
    (1003, "Lab", "Lab2", 42, 100),
    (1003, "Lab", "Lab3", 38, 100),
    (1003, "期中考", "期中考", 35, 100),
]

# ── db101 資料庫系統 ──
DB101_CATEGORIES = [
    {"name": "作業", "weight": 30},
    {"name": "期中考", "weight": 30},
    {"name": "專題", "weight": 40},
]

DB101_SCORES: list[tuple[int, str, str, float, float]] = [
    # 1001 A 陳同學 — mid-level DB
    (1001, "作業", "HW1", 75, 100),
    (1001, "作業", "HW2", 70, 100),
    (1001, "期中考", "期中考", 65, 100),
    # 1002 B 林同學 — strong in DB
    (1002, "作業", "HW1", 92, 100),
    (1002, "作業", "HW2", 88, 100),
    (1002, "期中考", "期中考", 90, 100),
    # 1003 C 王同學 — retake, basic level
    (1003, "作業", "HW1", 58, 100),
    (1003, "作業", "HW2", 52, 100),
    (1003, "期中考", "期中考", 48, 100),
    # 1004 D 李同學 — low engagement
    (1004, "作業", "HW1", 45, 100),
    (1004, "作業", "HW2", 30, 100),
    (1004, "期中考", "期中考", 25, 100),
    # 1005 E 張同學 — DB focus, does well here
    (1005, "作業", "HW1", 85, 100),
    (1005, "作業", "HW2", 88, 100),
    (1005, "期中考", "期中考", 82, 100),
]

# Courses to seed: (course_id, categories, scores)
_COURSE_DATA = [
    ("ds101", DS101_CATEGORIES, DS101_SCORES),
    ("py101", PY101_CATEGORIES, PY101_SCORES),
    ("db101", DB101_CATEGORIES, DB101_SCORES),
]


def seed_demo_grades(mgr: GradeManager) -> None:
    """Seed demo grade data into the GradeManager.

    Clears existing data and seeds fresh categories + scores for all courses.
    """
    for course_id, categories, scores in _COURSE_DATA:
        mgr.set_categories(course_id, categories)
        mgr._scores[course_id] = []

        for student_id, category, item, score, total in scores:
            mgr.record_score(
                course_id,
                student_id=student_id,
                category=category,
                item=item,
                score=score,
                total=total,
            )
