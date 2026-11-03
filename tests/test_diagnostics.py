"""Standalone diagnostic router tests with real JWTs and isolated databases."""

from __future__ import annotations

from eduinsight.courses import enroll

import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight import app as app_module
from eduinsight import auth, diagnostics, sessions
from eduinsight.analytics import assess_risk
from eduinsight.assistant import LearningAssistant
from eduinsight.config import settings
from eduinsight.documents import ParsedMarkdown, split_markdown_by_headings
from eduinsight.grades import GradeManager
from eduinsight.live_quiz import QuizSessionManager
from eduinsight.rag import CourseRAG

ENDPOINTS = ("overview", "hard-topics", "clusters")


@pytest.fixture
def diagnostic_app(monkeypatch):
    memory = Memory(settings.memory_db_path)
    monkeypatch.setattr(app_module, "_memory", memory)
    monkeypatch.setattr(app_module, "_assistant", LearningAssistant(memory))
    monkeypatch.setattr(app_module, "_rag", CourseRAG(memory))
    monkeypatch.setattr(app_module, "_llm", None)
    monkeypatch.setattr(app_module, "_quiz", None)
    monkeypatch.setattr(app_module, "_grades", GradeManager())
    monkeypatch.setattr(app_module, "_quiz_manager", QuizSessionManager())
    app = FastAPI()
    app.include_router(diagnostics.router)
    # Reuse the real demo handler without modifying the production route table.
    app.add_api_route("/demo/reset", app_module.demo_reset, methods=["POST"])
    return app


@pytest.fixture
async def client(diagnostic_app):
    async with AsyncClient(
        transport=ASGITransport(app=diagnostic_app), base_url="http://test",
    ) as test_client:
        yield test_client


def _message(memory, student_id, session_id, text, role="user"):
    memory._store.store_message(
        f"moodle:{student_id}", text, session_id=session_id, role=role,
    )


def _index(memory, course_id, filename, markdown):
    return CourseRAG(memory).index_markdown(course_id, ParsedMarkdown(
        filename=filename, markdown=markdown, total_pages=1,
        chunks=split_markdown_by_headings(markdown, source=filename),
    ))


@pytest.fixture
def evidence(diagnostic_app, auth_headers):
    memory = app_module._memory
    for student_id in (1001, 1002):
        enroll("ds101", student_id, source="test")
        session = sessions.create_session(student_id, "ds101")
        memory.add(f"moodle:{student_id}", "[SQL] Understands SELECT", extract=False)
        memory.add(
            f"moodle:{student_id}", "Struggling with JOIN: confused by NULL",
            category="struggling", extract=False,
        )
        _message(memory, student_id, session["session_id"], "How does JOIN handle NULL?")
    # Repeated evidence must not inflate distinct student counts or cluster sizes.
    memory.add("moodle:1001", "Struggling with join: left side confusion", extract=False)
    session = sessions.list_sessions(1001, "ds101")[0]
    name = auth.get_user_by_username("student1001")["display_name"]
    _message(
        memory, 1001, session["session_id"],
        f"I'm student1001 ({name}), ID 1001; contact me at learner@example.com. Why JOIN?",
    )
    _message(memory, 1001, session["session_id"], "JOIN assistant-only answer", "assistant")
    # Same learner's messages in other courses or unmapped sessions stay private.
    enroll("mk201", 1001, source="test")
    other = sessions.create_session(1001, "mk201")
    _message(memory, 1001, other["session_id"], "JOIN private other-course question")
    _message(memory, 1001, "unmapped", "JOIN private orphan question")
    # A forged student/session association must not expose another user's text.
    _message(memory, 1003, session["session_id"], "JOIN forged-owner question")
    enroll("mk201", 1003, source="test")
    sessions.create_session(1003, "mk201")
    memory.add("moodle:1003", "Struggling with SECRET: private topic", extract=False)
    _index(memory, "mk201", "private.md", "## JOIN\nJOIN private material")
    return memory


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_requires_authentication(client, endpoint):
    response = await client.get(f"/diagnostics/ds101/{endpoint}")
    assert response.status_code == 401


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_rejects_invalid_bearer(client, endpoint):
    response = await client.get(
        f"/diagnostics/ds101/{endpoint}", headers={"Authorization": "Bearer invalid"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_students_are_forbidden(client, auth_headers, endpoint):
    response = await client.get(
        f"/diagnostics/ds101/{endpoint}", headers=auth_headers("student1001"),
    )
    assert response.status_code == 403


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_teacher_course_scoping(client, auth_headers, endpoint):
    for teacher, allowed, forbidden in (
        ("teacher", "ds101", "mk201"), ("teacher_huang", "mk201", "ds101"),
    ):
        assert (await client.get(
            f"/diagnostics/{allowed}/{endpoint}", headers=auth_headers(teacher),
        )).status_code == 200
        assert (await client.get(
            f"/diagnostics/{forbidden}/{endpoint}", headers=auth_headers(teacher),
        )).status_code == 403


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_unmapped_teacher_is_forbidden(client, auth_headers, endpoint):
    auth.create_user(auth.RegisterRequest(
        username="unmapped", display_name="Unmapped teacher", password="test123", role="teacher",
    ))
    response = await client.get(
        f"/diagnostics/ds101/{endpoint}", headers=auth_headers("unmapped"),
    )
    assert response.status_code == 403


async def test_admin_empty_course(client, auth_headers):
    response = await client.get("/diagnostics/empty/overview", headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == {
        "course_id": "empty", "mastery_estimate": None, "total_students": 0,
        "total_facts": 0, "struggle_fact_count": 0, "at_risk_student_count": 0,
        "at_risk_student_ratio": 0, "active_learner_count": 0,
        "indexed_material_chunk_count": 0,
    }
    for endpoint in ("hard-topics", "clusters"):
        response = await client.get(f"/diagnostics/empty/{endpoint}", headers=auth_headers())
        assert response.status_code == 200
        assert response.json() == []


async def test_overview_uses_real_facts_and_material_chunks(client, auth_headers, evidence):
    chunks = _index(evidence, "ds101", "notes.md", "## JOIN\nJOIN NULL\n\n## SELECT\nSELECT rows")
    response = await client.get("/diagnostics/ds101/overview", headers=auth_headers("teacher"))
    assert response.status_code == 200
    data = response.json()
    assert data["mastery_estimate"] == 40
    assert data["total_students"] == 2
    assert data["total_facts"] == 5
    assert data["struggle_fact_count"] == 3
    assert data["active_learner_count"] == 2
    assert data["indexed_material_chunk_count"] == chunks == 2
    expected_risk = sum(
        assess_risk(evidence, student_id, class_avg_facts=2.5).risk_level != "low"
        for student_id in (1001, 1002)
    )
    assert data["at_risk_student_count"] == expected_risk
    assert data["at_risk_student_ratio"] == expected_risk / 2


async def test_topics_anonymize_real_course_questions(client, auth_headers, evidence):
    response = await client.get("/diagnostics/ds101/hard-topics", headers=auth_headers("teacher"))
    assert response.status_code == 200
    assert len(response.json()) == 1
    topic = response.json()[0]
    assert topic["topic"] == "JOIN"
    assert topic["student_count"] == 2
    assert topic["matched_material_locations"] == []
    assert len(topic["representative_questions"]) == 2
    assert "How does JOIN handle NULL?" in topic["representative_questions"]
    questions = " ".join(topic["representative_questions"])
    assert "[匿名]" in questions
    for secret in (
        "student1001", "1001", "learner@example.com", "private", "assistant-only", "forged-owner",
        auth.get_user_by_username("student1001")["display_name"],
    ):
        assert secret not in questions
    assert "username" not in topic


async def test_topics_return_real_markdown_locations(client, auth_headers, evidence):
    _index(evidence, "ds101", "notes.md", "## JOIN\nJOIN combines tables and handles NULL")
    response = await client.get("/diagnostics/ds101/hard-topics", headers=auth_headers("teacher"))
    assert response.status_code == 200
    locations = response.json()[0]["matched_material_locations"]
    assert locations == [{"filename": "notes.md", "page": None, "heading": "JOIN", "anchor_id": "join"}]


async def test_clusters_have_unique_members_and_stable_ids(client, auth_headers, evidence):
    path = "/diagnostics/ds101/clusters"
    first = await client.get(path, headers=auth_headers("teacher"))
    assert first.status_code == 200
    assert len(first.json()) == 1
    cluster = first.json()[0]
    assert cluster["topic"] == "JOIN"
    assert cluster["size"] == 2
    assert cluster["members"] == [
        {"moodle_user_id": student_id,
         "display_name": auth.get_user_by_username(f"student{student_id}")["display_name"]}
        for student_id in (1001, 1002)
    ]
    assert "JOIN" in cluster["suggested_intervention"]
    assert "2" in cluster["suggested_intervention"]
    second = await client.get(path, headers=auth_headers())
    assert second.json() == first.json()
    other = await client.get("/diagnostics/mk201/clusters", headers=auth_headers())
    assert {group["topic"] for group in other.json()} == {"JOIN", "SECRET"}
    other_join = next(group for group in other.json() if group["topic"] == "JOIN")
    assert other_join["cluster_id"] != cluster["cluster_id"]


async def test_empty_sessions_do_not_count_as_active(client, auth_headers):
    enroll("ds101", 1001, source="test")
    sessions.create_session(1001, "ds101")
    response = await client.get("/diagnostics/ds101/overview", headers=auth_headers("teacher"))
    assert response.status_code == 200
    data = response.json()
    assert data["mastery_estimate"] is None
    assert data["total_students"] == 1
    assert data["active_learner_count"] == 0
    assert data["at_risk_student_ratio"] == 1
    assert data["at_risk_student_count"] == 1


async def test_active_learners_include_course_messages_but_not_other_course(client, auth_headers):
    memory = app_module._memory
    enroll("ds101", 1001, source="test")
    current = sessions.create_session(1001, "ds101")
    enroll("ds101", 1002, source="test")
    sessions.create_session(1002, "ds101")
    enroll("mk201", 1002, source="test")
    other = sessions.create_session(1002, "mk201")
    memory.add("moodle:1002", "[SQL] Old SELECT knowledge", extract=False)
    conn = memory._store._get_conn()
    conn.execute("UPDATE facts SET created_at = ? WHERE user_id = ?", (time.time() - 30 * 86400, "moodle:1002"))
    conn.commit()
    _message(memory, 1001, current["session_id"], "What is JOIN?")
    _message(memory, 1002, other["session_id"], "Recent private question")
    response = await client.get("/diagnostics/ds101/overview", headers=auth_headers("teacher"))
    assert response.status_code == 200
    assert response.json()["active_learner_count"] == 1


async def test_demo_reset_data_is_visible_to_standalone_router(client, auth_headers):
    original_memory = app_module._memory
    response = await client.post("/demo/reset", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["students_seeded"] == 5
    assert app_module._memory is not original_memory
    overview = await client.get("/diagnostics/ds101/overview", headers=auth_headers("teacher"))
    assert overview.status_code == 200
    data = overview.json()
    assert data["total_students"] == 5
    assert data["total_facts"] == response.json()["total_memories"]
    assert 0 < data["mastery_estimate"] < 100
    assert data["indexed_material_chunk_count"] > 0
    assert data["at_risk_student_count"] >= 1
    assert data["at_risk_student_ratio"] == data["at_risk_student_count"] / 5
    assert data["active_learner_count"] == 4
    topics = await client.get("/diagnostics/ds101/hard-topics", headers=auth_headers("teacher"))
    assert topics.status_code == 200
    assert topics.json()
    for topic in topics.json():
        assert topic["student_count"] > 0
        # Demo messages lack matching course session IDs, so no invented excerpts.
        assert topic["representative_questions"] == []
        for location in topic["matched_material_locations"]:
            assert location["filename"] == "ds101_lecture_notes.pdf"
            assert location["page"] is not None
    groups = await client.get("/diagnostics/ds101/clusters", headers=auth_headers("teacher"))
    assert groups.status_code == 200
    assert groups.json()
    for group in groups.json():
        assert group["size"] == len(group["members"])
        assert all(1001 <= member["moodle_user_id"] <= 1005 for member in group["members"])
        assert group["suggested_intervention"]
