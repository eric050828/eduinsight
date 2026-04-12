"""Tests for grade management system."""

from __future__ import annotations

import pytest

from eduinsight.grades import GradeManager

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def mgr() -> GradeManager:
    return GradeManager()


@pytest.fixture
def mgr_with_cats(mgr: GradeManager) -> GradeManager:
    """Manager with CS101 categories already set up."""
    mgr.set_categories("CS101", [
        {"name": "作業", "weight": 30},
        {"name": "期中考", "weight": 30},
        {"name": "期末考", "weight": 40},
    ])
    return mgr


# ------------------------------------------------------------------
# Category configuration
# ------------------------------------------------------------------


class TestCategories:
    def test_set_categories(self, mgr: GradeManager):
        cats = mgr.set_categories("CS101", [
            {"name": "作業", "weight": 30},
            {"name": "期中考", "weight": 30},
            {"name": "期末考", "weight": 40},
        ])
        assert len(cats) == 3
        assert cats[0].name == "作業"
        assert cats[0].weight == 30

    def test_get_categories(self, mgr_with_cats: GradeManager):
        cats = mgr_with_cats.get_categories("CS101")
        assert len(cats) == 3

    def test_get_categories_not_found(self, mgr: GradeManager):
        with pytest.raises(KeyError):
            mgr.get_categories("NONEXISTENT")

    def test_empty_categories_raises(self, mgr: GradeManager):
        with pytest.raises(ValueError, match="At least one"):
            mgr.set_categories("CS101", [])

    def test_weights_not_100_raises(self, mgr: GradeManager):
        with pytest.raises(ValueError, match="sum to 100"):
            mgr.set_categories("CS101", [
                {"name": "作業", "weight": 30},
                {"name": "期中考", "weight": 30},
            ])

    def test_negative_weight_raises(self, mgr: GradeManager):
        with pytest.raises(ValueError, match="must be positive"):
            mgr.set_categories("CS101", [
                {"name": "作業", "weight": -10},
                {"name": "期末考", "weight": 110},
            ])

    def test_empty_name_raises(self, mgr: GradeManager):
        with pytest.raises(ValueError, match="name cannot be empty"):
            mgr.set_categories("CS101", [{"name": "", "weight": 100}])

    def test_overwrite_categories(self, mgr_with_cats: GradeManager):
        """Setting categories again overwrites the old ones."""
        mgr_with_cats.set_categories("CS101", [
            {"name": "全部", "weight": 100},
        ])
        cats = mgr_with_cats.get_categories("CS101")
        assert len(cats) == 1
        assert cats[0].name == "全部"


# ------------------------------------------------------------------
# Score recording
# ------------------------------------------------------------------


class TestScoreRecording:
    def test_record_score(self, mgr_with_cats: GradeManager):
        rec = mgr_with_cats.record_score(
            "CS101", student_id=2001, category="作業", item="HW1", score=85
        )
        assert rec.score == 85
        assert rec.total == 100
        assert rec.category == "作業"
        assert rec.record_id.startswith("score_")

    def test_invalid_category_raises(self, mgr_with_cats: GradeManager):
        with pytest.raises(ValueError, match="not found"):
            mgr_with_cats.record_score(
                "CS101", student_id=2001, category="不存在", item="X", score=50
            )

    def test_no_categories_raises(self, mgr: GradeManager):
        with pytest.raises(KeyError):
            mgr.record_score(
                "CS101", student_id=2001, category="作業", item="HW1", score=50
            )

    def test_score_exceeds_total_raises(self, mgr_with_cats: GradeManager):
        with pytest.raises(ValueError, match="exceeds total"):
            mgr_with_cats.record_score(
                "CS101", student_id=2001, category="作業", item="HW1",
                score=110, total=100,
            )

    def test_negative_score_raises(self, mgr_with_cats: GradeManager):
        with pytest.raises(ValueError, match="negative"):
            mgr_with_cats.record_score(
                "CS101", student_id=2001, category="作業", item="HW1", score=-5
            )

    def test_zero_total_raises(self, mgr_with_cats: GradeManager):
        with pytest.raises(ValueError, match="Total must be positive"):
            mgr_with_cats.record_score(
                "CS101", student_id=2001, category="作業", item="HW1",
                score=0, total=0,
            )

    def test_duplicate_item_updates(self, mgr_with_cats: GradeManager):
        """Recording same student+category+item updates the score."""
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="作業", item="HW1", score=70
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="作業", item="HW1", score=85
        )
        scores = mgr_with_cats.get_scores("CS101", student_id=2001, category="作業")
        assert len(scores) == 1
        assert scores[0].score == 85

    def test_get_scores_filtered(self, mgr_with_cats: GradeManager):
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="作業", item="HW1", score=80
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="期中考", item="Midterm", score=75
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2002, category="作業", item="HW1", score=90
        )
        # Filter by student
        s1 = mgr_with_cats.get_scores("CS101", student_id=2001)
        assert len(s1) == 2
        # Filter by category
        hw = mgr_with_cats.get_scores("CS101", category="作業")
        assert len(hw) == 2
        # Filter by both
        s1hw = mgr_with_cats.get_scores("CS101", student_id=2001, category="作業")
        assert len(s1hw) == 1

    def test_delete_score(self, mgr_with_cats: GradeManager):
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="作業", item="HW1", score=80
        )
        deleted = mgr_with_cats.delete_score(
            "CS101", student_id=2001, category="作業", item="HW1"
        )
        assert deleted is True
        assert len(mgr_with_cats.get_scores("CS101", student_id=2001)) == 0

    def test_delete_nonexistent_score(self, mgr_with_cats: GradeManager):
        deleted = mgr_with_cats.delete_score(
            "CS101", student_id=2001, category="作業", item="HW1"
        )
        assert deleted is False


# ------------------------------------------------------------------
# Student summary
# ------------------------------------------------------------------


class TestStudentSummary:
    def test_empty_summary(self, mgr_with_cats: GradeManager):
        summary = mgr_with_cats.student_summary("CS101", 2001)
        assert summary.weighted_total == 0.0
        assert len(summary.categories) == 3

    def test_weighted_total_single_category(self, mgr_with_cats: GradeManager):
        # 作業 weight=30, score=80/100 → contribution = 80 * 30/100 = 24
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="作業", item="HW1", score=80
        )
        summary = mgr_with_cats.student_summary("CS101", 2001)
        assert summary.weighted_total == 24.0

    def test_weighted_total_all_categories(self, mgr_with_cats: GradeManager):
        # 作業 30%: 80 → 24
        # 期中考 30%: 70 → 21
        # 期末考 40%: 90 → 36
        # Total: 81
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="作業", item="HW1", score=80
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="期中考", item="Midterm", score=70
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="期末考", item="Final", score=90
        )
        summary = mgr_with_cats.student_summary("CS101", 2001)
        assert summary.weighted_total == 81.0

    def test_multiple_items_averaged(self, mgr_with_cats: GradeManager):
        # 作業 weight=30, two items: 80 and 60 → avg 70% → contribution = 70 * 30/100 = 21
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="作業", item="HW1", score=80
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="作業", item="HW2", score=60
        )
        summary = mgr_with_cats.student_summary("CS101", 2001)
        hw_cat = [c for c in summary.categories if c.category == "作業"][0]
        assert hw_cat.average_pct == 70.0
        assert hw_cat.weighted_contribution == 21.0

    def test_custom_total(self, mgr_with_cats: GradeManager):
        # Score 8/10 = 80% with weight 30 → 24
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="作業", item="HW1",
            score=8, total=10,
        )
        summary = mgr_with_cats.student_summary("CS101", 2001)
        hw_cat = [c for c in summary.categories if c.category == "作業"][0]
        assert hw_cat.average_pct == 80.0

    def test_summary_with_rank(self, mgr_with_cats: GradeManager):
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="期末考", item="Final", score=90
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2002, category="期末考", item="Final", score=70
        )
        summary = mgr_with_cats.student_summary_with_rank("CS101", 2001)
        assert summary.rank == 1
        assert summary.total_students == 2


# ------------------------------------------------------------------
# Class overview
# ------------------------------------------------------------------


class TestClassOverview:
    def test_empty_class(self, mgr_with_cats: GradeManager):
        overview = mgr_with_cats.class_overview("CS101")
        assert overview.total_students == 0
        assert overview.mean == 0.0
        assert overview.rankings == []

    def test_class_stats(self, mgr_with_cats: GradeManager):
        # Student 1: 期末考 90 → weighted 36
        # Student 2: 期末考 70 → weighted 28
        # Student 3: 期末考 80 → weighted 32
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="期末考", item="Final", score=90
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2002, category="期末考", item="Final", score=70
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2003, category="期末考", item="Final", score=80
        )
        overview = mgr_with_cats.class_overview("CS101")
        assert overview.total_students == 3
        assert overview.mean == 32.0
        assert overview.median == 32.0

    def test_rankings_ordered(self, mgr_with_cats: GradeManager):
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="期末考", item="Final", score=70
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2002, category="期末考", item="Final", score=90
        )
        overview = mgr_with_cats.class_overview("CS101")
        assert overview.rankings[0]["student_id"] == 2002
        assert overview.rankings[0]["rank"] == 1
        assert overview.rankings[1]["student_id"] == 2001
        assert overview.rankings[1]["rank"] == 2

    def test_tie_handling(self, mgr_with_cats: GradeManager):
        mgr_with_cats.record_score(
            "CS101", student_id=2001, category="期末考", item="Final", score=80
        )
        mgr_with_cats.record_score(
            "CS101", student_id=2002, category="期末考", item="Final", score=80
        )
        overview = mgr_with_cats.class_overview("CS101")
        assert overview.rankings[0]["rank"] == 1
        assert overview.rankings[1]["rank"] == 1  # tie

    def test_distribution(self, mgr_with_cats: GradeManager):
        # Using only 期末考 (40% weight):
        # 100 * 40% = 40 → F band (< 60)
        # But let's use all categories for a full-score student
        mgr = GradeManager()
        mgr.set_categories("CS101", [{"name": "全部", "weight": 100}])
        mgr.record_score("CS101", student_id=2001, category="全部", item="Total", score=95)
        mgr.record_score("CS101", student_id=2002, category="全部", item="Total", score=85)
        mgr.record_score("CS101", student_id=2003, category="全部", item="Total", score=72)
        mgr.record_score("CS101", student_id=2004, category="全部", item="Total", score=55)
        overview = mgr.class_overview("CS101")
        assert overview.distribution["A"] == 1  # 95
        assert overview.distribution["B"] == 1  # 85
        assert overview.distribution["C"] == 1  # 72
        assert overview.distribution["F"] == 1  # 55

    def test_no_categories_raises(self, mgr: GradeManager):
        with pytest.raises(KeyError):
            mgr.class_overview("NONEXISTENT")

    def test_list_courses(self, mgr_with_cats: GradeManager):
        courses = mgr_with_cats.list_courses()
        assert "CS101" in courses


# ------------------------------------------------------------------
# API tests
# ------------------------------------------------------------------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from eduinsight.app import app

    with TestClient(app) as c:
        yield c


class TestGradeAPI:
    def _setup_course(self, client) -> list[dict]:
        """Set up CS101 with 3 categories."""
        resp = client.post(
            "/grades/CS101/categories",
            json={
                "categories": [
                    {"name": "作業", "weight": 30},
                    {"name": "期中考", "weight": 30},
                    {"name": "期末考", "weight": 40},
                ]
            },
        )
        assert resp.status_code == 200
        return resp.json()

    def test_set_categories(self, client):
        cats = self._setup_course(client)
        assert len(cats) == 3
        assert cats[0]["name"] == "作業"

    def test_set_categories_bad_weights(self, client):
        resp = client.post(
            "/grades/CS101/categories",
            json={"categories": [{"name": "X", "weight": 50}]},
        )
        assert resp.status_code == 400

    def test_get_categories(self, client):
        self._setup_course(client)
        resp = client.get("/grades/CS101/categories")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_get_categories_not_found(self, client):
        resp = client.get("/grades/NONE/categories")
        assert resp.status_code == 404

    def test_record_score(self, client):
        self._setup_course(client)
        resp = client.post(
            "/grades/CS101/scores",
            json={"student_id": 2001, "category": "作業", "item": "HW1", "score": 85},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] == 85
        assert data["category"] == "作業"

    def test_record_score_bad_category(self, client):
        self._setup_course(client)
        resp = client.post(
            "/grades/CS101/scores",
            json={"student_id": 2001, "category": "不存在", "item": "X", "score": 50},
        )
        assert resp.status_code == 400

    def test_get_scores(self, client):
        self._setup_course(client)
        client.post(
            "/grades/CS101/scores",
            json={"student_id": 2001, "category": "作業", "item": "HW1", "score": 80},
        )
        client.post(
            "/grades/CS101/scores",
            json={"student_id": 2001, "category": "期中考", "item": "Midterm", "score": 75},
        )
        resp = client.get("/grades/CS101/scores?student_id=2001")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_delete_score(self, client):
        self._setup_course(client)
        client.post(
            "/grades/CS101/scores",
            json={"student_id": 2001, "category": "作業", "item": "HW1", "score": 80},
        )
        resp = client.request(
            "DELETE",
            "/grades/CS101/scores",
            json={"student_id": 2001, "category": "作業", "item": "HW1"},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_student_grades(self, client):
        self._setup_course(client)
        client.post(
            "/grades/CS101/scores",
            json={"student_id": 2001, "category": "作業", "item": "HW1", "score": 80},
        )
        client.post(
            "/grades/CS101/scores",
            json={"student_id": 2001, "category": "期末考", "item": "Final", "score": 90},
        )
        resp = client.get("/grades/CS101/student/2001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["weighted_total"] > 0
        assert len(data["categories"]) == 3

    def test_class_overview(self, client):
        self._setup_course(client)
        client.post(
            "/grades/CS101/scores",
            json={"student_id": 2001, "category": "期末考", "item": "Final", "score": 90},
        )
        client.post(
            "/grades/CS101/scores",
            json={"student_id": 2002, "category": "期末考", "item": "Final", "score": 70},
        )
        resp = client.get("/grades/CS101/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_students"] == 2
        assert len(data["rankings"]) == 2

    def test_list_courses(self, client):
        self._setup_course(client)
        resp = client.get("/grades/courses")
        assert resp.status_code == 200
        assert "CS101" in resp.json()
