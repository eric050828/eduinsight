"""Real JWTs, temporary databases, and a small app for the extra router."""

from datetime import UTC, datetime, timedelta

import eduinsight.app as app_module
import pytest
from eduinsight import analytics_extra as extra
from eduinsight import assignments, auth, sessions
from eduinsight.assistant import LearningAssistant
from eduinsight.config import settings
from eduinsight.grades import GradeManager
from eduinsight.live_quiz import QuizSessionManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from litemem import Memory

_NOW = datetime(2026, 10, 9, 12, tzinfo=extra._TAIPEI)
_STUDENT_PATHS = (
    "/analytics-extra/student/1001/weekly-hours",
    "/analytics-extra/student/1001/focus-heatmap",
    "/analytics-extra/student/1001/skills",
    "/analytics-extra/student/1001/assignment-completion",
)
_OVERVIEW = "/analytics-extra/course/ds101/student/1001/overview"


@pytest.fixture
async def client(auth_headers, monkeypatch):
    memory = Memory(settings.memory_db_path, embedder=None)
    monkeypatch.setattr(app_module, "_memory", memory)
    monkeypatch.setattr(app_module, "_assistant", LearningAssistant(memory))
    monkeypatch.setattr(app_module, "_grades", GradeManager())
    monkeypatch.setattr(app_module, "_llm", None)
    monkeypatch.setattr(app_module, "_rag", None)
    monkeypatch.setattr(app_module, "_quiz", None)
    monkeypatch.setattr(app_module, "_quiz_manager", QuizSessionManager())
    monkeypatch.setattr(settings, "memory_embedder", "")
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(assignments.router)
    app.include_router(extra.router)
    # Invoke the real reset endpoint, retaining its actual role dependency,
    # without changing the production app or registering our router there.
    app.add_api_route("/demo/reset", app_module.demo_reset, methods=["POST"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def seed_session(sid="own", student=1001, course="ds101", start=None, end=None):
    start = _NOW.timestamp() if start is None else start
    end = start if end is None else end
    with sessions._db() as conn:
        conn.execute(
            "INSERT INTO chat_sessions VALUES (?, ?, ?, ?, ?, ?)",
            (sid, student, course, "Test", start, end),
        )
        conn.commit()
    return sid


def message(content, *, sid="own", student=1001, when=None, role="user"):
    store = app_module._memory._store
    msg_id = store.store_message(f"moodle:{student}", content, session_id=sid, role=role)
    conn = store._get_conn()
    conn.execute(
        "UPDATE messages SET created_at = ? WHERE id = ?",
        (_NOW.timestamp() if when is None else when, msg_id),
    )
    conn.commit()


async def get(client, auth_headers, path, username="student1001"):
    response = await client.get(path, headers=auth_headers(username))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("path", (*_STUDENT_PATHS, _OVERVIEW))
@pytest.mark.parametrize("headers", ({}, {"Authorization": "Bearer invalid"}))
async def test_requires_valid_auth(client, path, headers):
    assert (await client.get(path, headers=headers)).status_code == 401


@pytest.mark.parametrize("path", _STUDENT_PATHS)
async def test_student_ownership_and_moodle_identity(client, auth_headers, path):
    assert (await client.get(path, headers=auth_headers("student1002"))).status_code == 403
    row = auth.get_user_by_username("student1001")
    assert row["id"] != row["moodle_user_id"]
    own = await get(client, auth_headers, path)
    assert own["moodle_user_id"] == 1001
    wrong_id = path.replace("/1001/", f"/{row['id']}/")
    assert (await client.get(wrong_id, headers=auth_headers("student1001"))).status_code == 403


@pytest.mark.parametrize("path", _STUDENT_PATHS)
async def test_teacher_enrollment_and_unmapped_teacher(client, auth_headers, path):
    seed_session(course="mk201")
    assert (await client.get(path, headers=auth_headers("teacher"))).status_code == 403
    assert (await client.get(path, headers=auth_headers("teacher_huang"))).status_code == 200
    assert (await client.get(path, headers=auth_headers())).status_code == 200
    auth.create_user(
        auth.RegisterRequest(
            username="unmapped",
            password="test123",
            display_name="Unmapped",
            role="teacher",
        )
    )
    assert (await client.get(path, headers=auth_headers("unmapped"))).status_code == 403


async def test_overview_role_course_and_enrollment_guards(client, auth_headers):
    seed_session()
    assert (await client.get(_OVERVIEW, headers=auth_headers("student1001"))).status_code == 403
    assert (await client.get(_OVERVIEW, headers=auth_headers("teacher_huang"))).status_code == 403
    assert (await client.get(_OVERVIEW, headers=auth_headers("teacher"))).status_code == 200
    assert (await client.get(_OVERVIEW, headers=auth_headers())).status_code == 200
    absent = _OVERVIEW.replace("/1001/", "/1002/")
    assert (await client.get(absent, headers=auth_headers())).status_code == 403
    unknown = _OVERVIEW.replace("/ds101/", "/unknown/")
    assert (await client.get(unknown, headers=auth_headers())).status_code == 404


async def test_empty_data_shapes(client, auth_headers):
    weekly = await get(client, auth_headers, _STUDENT_PATHS[0])
    assert weekly["estimated"] is True and weekly["timezone"] == "Asia/Taipei"
    assert len(weekly["weeks"]) == 8
    assert all(row["hours"] == 0 for row in weekly["weeks"])
    assert all(datetime.fromisoformat(row["week_start"]).weekday() == 0 for row in weekly["weeks"])
    heatmap = await get(client, auth_headers, _STUDENT_PATHS[1])
    assert heatmap["weekday_order"] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert heatmap["counts"] == [[0] * 24 for _ in range(7)]
    assert (await get(client, auth_headers, _STUDENT_PATHS[2]))["skills"] == []
    assert (await get(client, auth_headers, _STUDENT_PATHS[3]))["courses"] == []
    seed_session()
    overview = await get(client, auth_headers, _OVERVIEW, "teacher")
    assert overview["course_rank"] is None and overview["grade_average"] is None
    assert overview["ranked_students"] == 0 and overview["knowledge_mastery"] == []
    assert overview["intent_summary"] == {
        "概念釐清": 0,
        "除錯": 0,
        "作業協助": 0,
        "考試準備": 0,
        "其他": 0,
    }
    assert (await get(client, auth_headers, _STUDENT_PATHS[3]))["courses"] == [
        {"course_id": "ds101", "total": 0, "submitted": 0, "graded": 0, "overdue": 0},
    ]


async def test_weekly_union_boundaries_idle_gaps_and_course_scope(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(extra, "_now", lambda: _NOW)
    monday = datetime(2026, 10, 5, tzinfo=extra._TAIPEI).timestamp()
    seed_session(start=monday - 600, end=monday + 600)
    seed_session("overlap", start=monday - 300, end=monday + 900)
    seed_session("idle", start=monday - 86400, end=monday)
    seed_session("other", course="mk201", start=monday + 3600, end=monday + 5400)
    seed_session("other-student", student=1002, start=monday + 3600, end=monday + 5400)
    seed_session("old", start=monday - 70 * 86400, end=monday - 70 * 86400 + 600)
    seed_session("future", start=_NOW.timestamp() - 300, end=_NOW.timestamp() + 300)
    teacher = await get(client, auth_headers, _STUDENT_PATHS[0], "teacher")
    assert teacher["weeks"][-2] == {"week_start": "2026-09-28", "hours": 0.1667}
    assert teacher["weeks"][-1] == {"week_start": "2026-10-05", "hours": 0.3333}
    assert all(row["hours"] == 0 for row in teacher["weeks"][:-2])
    own = await get(client, auth_headers, _STUDENT_PATHS[0])
    assert own["weeks"][-1]["hours"] == 0.8333
    assert own == await get(client, auth_headers, _STUDENT_PATHS[0], "admin")


async def test_message_activity_heatmap_and_idle_session(client, auth_headers, monkeypatch):
    monkeypatch.setattr(extra, "_now", lambda: _NOW)
    monday = datetime(2026, 10, 5, 0, 10, tzinfo=extra._TAIPEI).timestamp()
    seed_session(start=monday - 86400, end=monday + 86400)
    for offset in (0, 600, 7200, 7500):
        message("hello", when=monday + offset)
    message("assistant must not count", when=monday + 600, role="assistant")
    message("other student", when=monday, student=1002)
    message("orphan", sid="legacy", when=monday)
    message("future", when=_NOW.timestamp() + 600)
    seed_session("mk", course="mk201")
    message("course secret", sid="mk", when=monday + 3600)
    teacher = await get(client, auth_headers, _STUDENT_PATHS[0], "teacher")
    assert teacher["weeks"][-1]["hours"] == 0.25  # ten + five minutes, two-hour gap excluded
    heatmap = await get(client, auth_headers, _STUDENT_PATHS[1], "teacher")
    assert heatmap["counts"][0][0] == 2 and heatmap["counts"][0][2] == 2
    assert sum(map(sum, heatmap["counts"])) == 4
    own = await get(client, auth_headers, _STUDENT_PATHS[1])
    assert own["counts"][0][0] == 3 and own["counts"][0][1] == 1
    assert sum(map(sum, own["counts"])) == 6


async def test_metadata_heatmap_has_no_empty_session_activity(client, auth_headers, monkeypatch):
    monkeypatch.setattr(extra, "_now", lambda: _NOW)
    seed_session()
    seed_session("activity", start=_NOW.timestamp() - 600, end=_NOW.timestamp())
    heatmap = await get(client, auth_headers, _STUDENT_PATHS[1])
    assert heatmap["counts"][4][12] == 1
    assert sum(map(sum, heatmap["counts"])) == 1


async def test_skills_evidence_and_matrix_not_neutral_mastery(client, auth_headers):
    seed_session()
    memory = app_module._memory
    for text, category in (
        ("Struggling with: BST — can't understand traversal", "struggling"),
        ("Mastered BST: solved traversal", "mastered"),
        ("[SQL] SELECT syntax: an explanation", "general"),
        ("[Loops] Practice: 已掌握 for loop", "general"),
        ("[Lists] Practice: 尚未掌握 linked list", "general"),
        ("Learning preference: visual examples", "preference"),
    ):
        memory.add("moodle:1001", text, category=category, extract=False)
    memory.add(
        "moodle:1002", "Mastered SECRET: other user's fact", category="mastered", extract=False
    )
    result = await get(client, auth_headers, _STUDENT_PATHS[2])
    radar = {row["topic"]: row for row in result["skills"]}
    assert result["memory_scope"] == "student"
    assert set(radar) == {"BST", "SQL", "Loops", "Lists"}
    assert radar["BST"]["score"] == 50 and radar["BST"]["status"] == "mixed"
    assert radar["Loops"]["score"] == 100 and radar["Loops"]["mastered"] == 1
    assert radar["Lists"]["score"] == 0 and radar["Lists"]["struggling"] == 1
    assert radar["SQL"]["score"] == 0 and radar["SQL"]["unknown"] == 1
    overview = await get(client, auth_headers, _OVERVIEW, "teacher")
    assert overview["knowledge_scope"] == "student"
    assert overview["knowledge_mastery"] == result["skills"]


async def create_work(client, auth_headers, *, course="ds101", due=None):
    response = await client.post(
        "/assignments",
        headers=auth_headers(),
        json={
            "course_id": course,
            "title": "Work",
            "due_at": (due or datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "allow_late": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_assignment_counts_real_states_and_student_course_isolation(client, auth_headers):
    seed_session()
    seed_session("mk", course="mk201")
    seed_session("other", student=1002)
    past = datetime.now(UTC) - timedelta(days=1)
    graded = await create_work(client, auth_headers, due=past)
    submitted = await create_work(client, auth_headers)
    draft = await create_work(client, auth_headers, due=past)
    await create_work(client, auth_headers, due=past)  # overdue, no submission
    await create_work(client, auth_headers, course="mk201")
    for work, state in ((graded, "submitted"), (submitted, "submitted"), (draft, "draft")):
        response = await client.put(
            f"/assignments/{work}/submission",
            headers=auth_headers("student1001"),
            json={"text": "answer", "state": state},
        )
        assert response.status_code == 200
    response = await client.post(
        f"/assignments/{graded}/submissions/1001/grade",
        headers=auth_headers("teacher"),
        json={"score": 80},
    )
    assert response.status_code == 200
    teacher = await get(client, auth_headers, _STUDENT_PATHS[3], "teacher")
    assert teacher["courses"] == [
        {"course_id": "ds101", "total": 4, "submitted": 2, "graded": 1, "overdue": 2},
    ]
    own = await get(client, auth_headers, _STUDENT_PATHS[3])
    assert len(own["courses"]) == 2 and own["courses"][0] == teacher["courses"][0]
    other = await get(
        client, auth_headers, _STUDENT_PATHS[3].replace("1001", "1002"), "student1002"
    )
    assert other["courses"][0]["submitted"] == 0 and other["courses"][0]["graded"] == 0
    overview = await get(client, auth_headers, _OVERVIEW, "teacher")
    assert overview["course_rank"] == 1 and overview["grade_average"] == 80


async def test_grade_averages_ties_missing_grades_and_enrollment(client, auth_headers):
    for student in (1001, 1002, 1003, 1004):
        seed_session(str(student), student=student)
    grades = app_module._grades
    grades.set_categories("ds101", [{"name": "Quiz", "weight": 100}])
    for student, score, total, item in (
        (1001, 40, 50, "a"),
        (1001, 100, 100, "b"),
        (1002, 90, 100, "a"),
        (1003, 95, 100, "a"),
        (9999, 100, 100, "a"),
    ):
        grades.record_score(
            "ds101", student_id=student, category="Quiz", item=item, score=score, total=total
        )
    grades.set_categories("mk201", [{"name": "Quiz", "weight": 100}])
    grades.record_score("mk201", student_id=1001, category="Quiz", item="a", score=0)
    overview = await get(client, auth_headers, _OVERVIEW, "teacher")
    assert overview["course_rank"] == 2 and overview["grade_average"] == 90
    assert overview["ranked_students"] == 3
    tied = await get(client, auth_headers, _OVERVIEW.replace("1001", "1002"), "teacher")
    assert tied["course_rank"] == 2
    missing = await get(client, auth_headers, _OVERVIEW.replace("1001", "1004"), "teacher")
    assert missing["course_rank"] is None and missing["grade_average"] is None
    # Gradebook already has actual scores: assignment grades must not duplicate them.
    assignment = await create_work(client, auth_headers)
    await client.put(
        f"/assignments/{assignment}/submission",
        headers=auth_headers("student1001"),
        json={"state": "submitted"},
    )
    await client.post(
        f"/assignments/{assignment}/submissions/1001/grade",
        headers=auth_headers(),
        json={"score": 0},
    )
    assert (await get(client, auth_headers, _OVERVIEW, "teacher"))["grade_average"] == 90


async def test_intent_rules_priority_and_no_cross_course_messages(client, auth_headers):
    seed_session()
    seed_session("mk", course="mk201")
    for content in ("什麼是 BST", "DEBUG my homework", "請協助作業", "期中考試複習", "謝謝"):
        message(content)
    message("ERROR", role="assistant")
    message("SECRET ERROR", sid="mk")
    message("legacy exam", sid="missing")
    message("other exam", student=1002)
    result = await get(client, auth_headers, _OVERVIEW, "teacher")
    assert result["intent_summary"] == {
        "概念釐清": 1,
        "除錯": 1,
        "作業協助": 1,
        "考試準備": 1,
        "其他": 1,
    }
    assert (await get(client, auth_headers, _OVERVIEW, "admin"))["intent_summary"] == result[
        "intent_summary"
    ]


async def test_real_demo_reset_data_without_fabricated_mastery_or_activity(client, auth_headers):
    response = await client.post("/demo/reset", headers=auth_headers("student1001"))
    assert response.status_code == 403
    response = await client.post("/demo/reset", headers=auth_headers())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "seeded"
    weekly = await get(client, auth_headers, _STUDENT_PATHS[0])
    assert len(weekly["weeks"]) == 8 and all(row["hours"] == 0 for row in weekly["weeks"])
    heatmap = await get(client, auth_headers, _STUDENT_PATHS[1])
    user_messages = [
        row
        for row in extra.get_memory()._store.get_messages("moodle:1001")
        if row["role"] == "user"
    ]
    assert sum(map(sum, heatmap["counts"])) == len(user_messages) > 0
    skills = await get(client, auth_headers, _STUDENT_PATHS[2])
    assert skills["skills"] and all(row["score"] == 0 for row in skills["skills"])
    work = await get(client, auth_headers, _STUDENT_PATHS[3], "teacher")
    assert work["courses"] == [
        {"course_id": "ds101", "total": 3, "submitted": 1, "graded": 1, "overdue": 0},
    ]
    assert len((await get(client, auth_headers, _STUDENT_PATHS[3]))["courses"]) == 5
    overview = await get(client, auth_headers, _OVERVIEW, "teacher")
    scores = app_module._grades.get_scores("ds101", student_id=1001)
    expected = sum(100 * row.score / row.total for row in scores) / len(scores)
    assert overview["grade_average"] == round(expected, 2) and overview["course_rank"] is not None
    assert overview["knowledge_mastery"] == skills["skills"]
    # Demo conversations have legacy IDs without course mappings. Their intents
    # cannot honestly be attributed to ds101.
    assert sum(overview["intent_summary"].values()) == 0
