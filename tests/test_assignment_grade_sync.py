"""Grading an assignment submission shows up in the grade center (GradeManager)."""

from datetime import UTC, datetime, timedelta

import pytest
from eduinsight import analytics_extra, assignments, auth, sessions
from eduinsight.courses import enroll
from eduinsight.grades import GradeManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def manager(monkeypatch):
    fresh = GradeManager()
    monkeypatch.setattr(analytics_extra, "get_grade_manager", lambda: fresh)
    return fresh


@pytest.fixture
async def client(auth_headers, manager):
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(assignments.router)
    for student_id in (1001, 1002):
        enroll("ds101", student_id, source="test")
        sessions.create_session(student_id, "ds101")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def graded(client, auth_headers, title="排序比較", score=88, student="student1001"):
    created = await client.post("/assignments", headers=auth_headers("teacher"), json={
        "course_id": "ds101", "title": title, "max_score": 100,
        "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    })
    assert created.status_code == 201, created.text
    assignment_id = created.json()["id"]
    submitted = await client.put(
        f"/assignments/{assignment_id}/submission", headers=auth_headers(student),
        json={"text": "answer", "state": "submitted"},
    )
    assert submitted.status_code == 200, submitted.text
    student_id = int(student.removeprefix("student"))
    response = await client.post(
        f"/assignments/{assignment_id}/submissions/{student_id}/grade",
        headers=auth_headers("teacher"), json={"score": score},
    )
    assert response.status_code == 200, response.text
    return assignment_id


async def test_grading_creates_category_and_score(client, auth_headers, manager):
    await graded(client, auth_headers)
    assert [c.name for c in manager.get_categories("ds101")] == ["作業"]
    [record] = manager.get_scores("ds101", student_id=1001)
    assert (record.category, record.item, record.score, record.total) == ("作業", "排序比較", 88, 100)
    assert manager.student_summary("ds101", 1001).weighted_total == 88


async def test_regrading_updates_instead_of_duplicating(client, auth_headers, manager):
    assignment_id = await graded(client, auth_headers)
    response = await client.post(
        f"/assignments/{assignment_id}/submissions/1001/grade",
        headers=auth_headers("teacher"), json={"score": 70},
    )
    assert response.status_code == 200
    assert [r.score for r in manager.get_scores("ds101", student_id=1001)] == [70]


async def test_existing_categories_with_assignment_category_are_kept(client, auth_headers, manager):
    manager.set_categories("ds101", [{"name": "作業", "weight": 40}, {"name": "期末考", "weight": 60}])
    await graded(client, auth_headers)
    assert [(c.name, c.weight) for c in manager.get_categories("ds101")] == [("作業", 40), ("期末考", 60)]
    assert manager.student_summary("ds101", 1001).weighted_total == pytest.approx(88 * 0.4)


async def test_categories_without_assignment_category_are_left_alone(client, auth_headers, manager):
    manager.set_categories("ds101", [{"name": "期末考", "weight": 100}])
    await graded(client, auth_headers)
    assert manager.get_scores("ds101") == []


async def test_duplicate_titles_stay_separate(client, auth_headers, manager):
    await graded(client, auth_headers, title="練習")
    await graded(client, auth_headers, title="練習", score=60)
    items = sorted(r.item for r in manager.get_scores("ds101", student_id=1001))
    assert len(items) == 2 and all(item.startswith("練習（") for item in items)


async def test_resync_restores_grades_after_restart(client, auth_headers, manager, monkeypatch):
    await graded(client, auth_headers)
    restarted = GradeManager()
    monkeypatch.setattr(analytics_extra, "get_grade_manager", lambda: restarted)
    assert assignments.sync_grade_center() == 1
    assert restarted.student_summary("ds101", 1001).weighted_total == 88


async def test_rename_and_delete_follow_the_assignment(client, auth_headers, manager):
    assignment_id = await graded(client, auth_headers)
    renamed = await client.patch(
        f"/assignments/{assignment_id}", headers=auth_headers("teacher"), json={"title": "排序報告"},
    )
    assert renamed.status_code == 200
    assert [r.item for r in manager.get_scores("ds101")] == ["排序報告"]
    deleted = await client.delete(f"/assignments/{assignment_id}", headers=auth_headers("teacher"))
    assert deleted.status_code == 204
    assert manager.get_scores("ds101") == []
