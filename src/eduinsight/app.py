"""FastAPI application for EduInsight.

Provides REST endpoints for:
- Student chat interactions (with memory context)
- Moodle data retrieval (courses, assignments, grades)
- Health check
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from litemem import Memory
from litemem.portable import MemoryBundle
from pydantic import BaseModel

from .analytics import (
    ClassAnalytics,
    LearningTrajectory,
    StudentAnalytics,
    analyze_class,
    analyze_student,
    learning_trajectory,
)
from .assistant import LearningAssistant
from .config import settings
from .llm import ClaudeCLIClient, LLMClient, resolve_llm_config
from .lti import router as lti_router
from .moodle import MoodleClient

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Shared state (initialized at startup)
# ------------------------------------------------------------------
_memory: Memory | None = None
_assistant: LearningAssistant | None = None
_llm: LLMClient | None = None


def get_assistant() -> LearningAssistant:
    if _assistant is None:
        raise RuntimeError("Application not initialized")
    return _assistant


def get_moodle_client() -> MoodleClient:
    """Create a new MoodleClient from settings (caller must use as context manager)."""
    return MoodleClient(base_url=settings.moodle_url, token=settings.moodle_token)


# ------------------------------------------------------------------
# Lifespan
# ------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    global _memory, _assistant, _llm
    logger.info("Starting EduInsight with memory DB: %s", settings.memory_db_path)
    embedder = settings.memory_embedder or None  # "" means disabled
    _memory = Memory(settings.memory_db_path, embedder=embedder)

    # Try to initialize LLM: API key > Claude CLI > no LLM
    try:
        llm_config = resolve_llm_config()
        _llm = LLMClient(llm_config)
        await _llm.__aenter__()
        logger.info("LLM initialized: model=%s", llm_config.model)
    except ValueError:
        # Fallback: try claude CLI (uses Claude Code subscription)
        import shutil

        if shutil.which("claude"):
            _llm = ClaudeCLIClient(model="haiku")
            await _llm.__aenter__()
            logger.info("LLM initialized: Claude CLI (haiku)")
        else:
            logger.warning("No LLM API key or claude CLI found. /chat will return memory context only.")
            _llm = None

    _assistant = LearningAssistant(_memory, llm=_llm)
    yield

    logger.info("Shutting down EduInsight")
    if _llm is not None:
        await _llm.__aexit__(None, None, None)
        _llm = None
    _memory = None
    _assistant = None


# ------------------------------------------------------------------
# App
# ------------------------------------------------------------------

app = FastAPI(
    title="EduInsight",
    description="AI learning assistant for Moodle LMS",
    version="0.1.0",
    lifespan=lifespan,
)

_STATIC_DIR = Path(__file__).parent / "static"


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class ChatRequest(BaseModel):
    moodle_user_id: int
    message: str
    topic: str = ""


class ChatResponse(BaseModel):
    reply: str
    memory_context: list[str]


class RecordStruggleRequest(BaseModel):
    moodle_user_id: int
    topic: str
    details: str = ""


class StudentSummary(BaseModel):
    moodle_user_id: int
    fact_count: int
    oldest_ts: float | None = None
    newest_ts: float | None = None
    categories: dict[str, int] = {}


class TeacherDashboardResponse(BaseModel):
    total_students: int
    total_facts: int
    students: list[StudentSummary]


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Student sends a message; assistant responds with memory-augmented AI answer.

    If an LLM is configured, generates an AI answer using the student's
    memory context. Otherwise, falls back to returning context only.
    """
    assistant = get_assistant()

    if assistant._llm is not None:
        # Full AI answer with memory context
        response = await assistant.answer(
            req.moodle_user_id, req.message, topic=req.topic
        )
        return ChatResponse(reply=response.answer, memory_context=response.memory_context)

    # Fallback: no LLM configured, return context only
    context_texts = assistant.get_student_context(req.moodle_user_id, req.message)
    assistant.record_question(req.moodle_user_id, req.message, topic=req.topic)
    return ChatResponse(
        reply="[No LLM configured] Memory context retrieved. Set GEMINI_API_KEY to enable AI answers.",
        memory_context=context_texts,
    )


@app.post("/record-struggle")
async def record_struggle(req: RecordStruggleRequest) -> dict[str, str]:
    """Record that a student is struggling with a topic."""
    assistant = get_assistant()
    assistant.record_struggle(req.moodle_user_id, req.topic, req.details)
    return {"status": "recorded"}


@app.get("/courses/{moodle_user_id}")
async def get_courses(moodle_user_id: int) -> list[dict[str, Any]]:
    """Get courses for a Moodle user."""
    async with get_moodle_client() as client:
        try:
            courses = await client.get_user_courses(moodle_user_id)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Moodle API error: {e}")
    return [
        {
            "id": c.id,
            "shortname": c.shortname,
            "fullname": c.fullname,
            "summary": c.summary,
        }
        for c in courses
    ]


@app.get("/grades/{course_id}/{moodle_user_id}")
async def get_grades(course_id: int, moodle_user_id: int) -> list[dict[str, Any]]:
    """Get grades for a user in a course."""
    async with get_moodle_client() as client:
        try:
            grades = await client.get_grades(course_id, moodle_user_id)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Moodle API error: {e}")
    return [
        {
            "item_name": g.item_name,
            "grade": g.grade,
            "grade_max": g.grade_max,
            "feedback": g.feedback,
        }
        for g in grades
    ]


# ------------------------------------------------------------------
# Teacher dashboard endpoints
# ------------------------------------------------------------------


@app.get("/teacher/students", response_model=TeacherDashboardResponse)
async def teacher_students() -> TeacherDashboardResponse:
    """List all students with memory stats for the teacher dashboard."""
    assistant = get_assistant()
    mem = assistant.memory

    stats = mem.detailed_stats()
    students: list[StudentSummary] = []
    for u in stats.users:
        # Only include moodle-namespaced users
        if not u.user_id.startswith("moodle:"):
            continue
        moodle_id = int(u.user_id.removeprefix("moodle:"))
        students.append(
            StudentSummary(
                moodle_user_id=moodle_id,
                fact_count=u.fact_count,
                oldest_ts=u.oldest,
                newest_ts=u.newest,
                categories=u.categories,
            )
        )

    return TeacherDashboardResponse(
        total_students=len(students),
        total_facts=sum(s.fact_count for s in students),
        students=students,
    )


@app.get("/teacher/students/{moodle_user_id}/memories")
async def teacher_student_memories(moodle_user_id: int) -> dict[str, Any]:
    """Get all memories for a specific student (teacher view)."""
    assistant = get_assistant()
    memories = assistant.get_all_memories(moodle_user_id)
    return {
        "moodle_user_id": moodle_user_id,
        "count": len(memories),
        "memories": memories,
    }


# ------------------------------------------------------------------
# Analytics endpoints
# ------------------------------------------------------------------


class StruggleResponse(BaseModel):
    topic: str
    details: str = ""


class StudentAnalyticsResponse(BaseModel):
    moodle_user_id: int
    total_facts: int
    struggles: list[StruggleResponse]
    weak_topics: list[str]
    question_topics: dict[str, int]
    preferences: list[str]


class ClassAnalyticsResponse(BaseModel):
    total_students: int
    total_facts: int
    common_struggles: list[list[Any]]  # [[topic, count], ...]
    topic_distribution: dict[str, int]


@app.get("/analytics/student/{moodle_user_id}", response_model=StudentAnalyticsResponse)
async def get_student_analytics(moodle_user_id: int) -> StudentAnalyticsResponse:
    """Get learning analytics for a specific student."""
    assistant = get_assistant()
    sa = analyze_student(assistant.memory, moodle_user_id)
    return StudentAnalyticsResponse(
        moodle_user_id=sa.moodle_user_id,
        total_facts=sa.total_facts,
        struggles=[StruggleResponse(topic=s.topic, details=s.details) for s in sa.struggles],
        weak_topics=sa.weak_topics,
        question_topics=sa.question_topics,
        preferences=sa.preferences,
    )


class TrajectoryPointResponse(BaseModel):
    week_start: str
    new_facts: int
    new_struggles: list[str]
    new_topics: list[str]
    cumulative_facts: int
    cumulative_struggles: int


class TrajectoryResponse(BaseModel):
    moodle_user_id: int
    total_weeks: int
    points: list[TrajectoryPointResponse]


@app.get("/analytics/student/{moodle_user_id}/trajectory", response_model=TrajectoryResponse)
async def get_student_trajectory(moodle_user_id: int) -> TrajectoryResponse:
    """Get learning trajectory over time for a student."""
    assistant = get_assistant()
    traj = learning_trajectory(assistant.memory, moodle_user_id)
    return TrajectoryResponse(
        moodle_user_id=traj.moodle_user_id,
        total_weeks=traj.total_weeks,
        points=[
            TrajectoryPointResponse(
                week_start=p.week_start,
                new_facts=p.new_facts,
                new_struggles=p.new_struggles,
                new_topics=p.new_topics,
                cumulative_facts=p.cumulative_facts,
                cumulative_struggles=p.cumulative_struggles,
            )
            for p in traj.points
        ],
    )


@app.get("/analytics/class", response_model=ClassAnalyticsResponse)
async def get_class_analytics() -> ClassAnalyticsResponse:
    """Get class-wide learning analytics (common struggles, topic distribution)."""
    assistant = get_assistant()
    ca = analyze_class(assistant.memory)
    return ClassAnalyticsResponse(
        total_students=ca.total_students,
        total_facts=ca.total_facts,
        common_struggles=[[t, c] for t, c in ca.common_struggles],
        topic_distribution=ca.topic_distribution,
    )


# ------------------------------------------------------------------
# Demo endpoints
# ------------------------------------------------------------------


class DemoResetResponse(BaseModel):
    status: str
    students_seeded: int
    total_memories: int


@app.post("/demo/reset", response_model=DemoResetResponse)
async def demo_reset() -> DemoResetResponse:
    """Reset the database and seed demo data.

    This deletes all existing data and populates the database with
    4 demo students for walkthrough purposes.
    """
    global _memory, _assistant

    # Import seed data
    from .demo_data import DEMO_STUDENTS

    # Use Lite-Mem's own delete to clear, then re-seed
    db_path = settings.memory_db_path
    embedder = settings.memory_embedder or None

    # Clear all demo students' data via Lite-Mem API
    if _memory is not None:
        for uid in DEMO_STUDENTS:
            try:
                for fact in _memory.list(uid):
                    _memory.delete(uid, fact)
            except Exception:
                pass

    _memory = Memory(db_path, embedder=embedder)
    _assistant = LearningAssistant(_memory, llm=_llm)

    # Seed demo data (each fact is a (text, category) tuple)
    total_seeded = 0
    for user_id, facts in DEMO_STUDENTS.items():
        for fact_text, category in facts:
            _memory.add(user_id, fact_text, category=category)
        total_seeded += len(facts)

    # Verify actual stored count (Lite-Mem dedup may reduce it)
    actual_total = 0
    for user_id in DEMO_STUDENTS:
        actual_total += len(_memory.list(user_id))

    if actual_total < total_seeded:
        logger.warning(
            "Demo seed: %d facts seeded but only %d survived (Lite-Mem dedup)",
            total_seeded, actual_total,
        )

    return DemoResetResponse(
        status="seeded",
        students_seeded=len(DEMO_STUDENTS),
        total_memories=actual_total,
    )


class SemesterDemoResponse(BaseModel):
    status: str
    student_id: str
    weeks_seeded: int
    total_memories: int


@app.post("/demo/semester", response_model=SemesterDemoResponse)
async def demo_semester() -> SemesterDemoResponse:
    """Seed a semester-long demo for student 2001 with time-spread data.

    Creates 18 weeks of learning interactions with backdated timestamps
    to demonstrate learning trajectory and memory accumulation over time.
    """
    global _memory, _assistant
    import time as _time

    from .semester_demo import SEMESTER_STUDENT_ID, SEMESTER_WEEKS

    db_path = settings.memory_db_path
    embedder = settings.memory_embedder or None

    # Clear existing data for this student
    if _memory is not None:
        try:
            for fact in _memory.list(SEMESTER_STUDENT_ID):
                _memory.delete(SEMESTER_STUDENT_ID, fact)
        except Exception:
            pass

    _memory = Memory(db_path, embedder=embedder)
    _assistant = LearningAssistant(_memory, llm=_llm)

    # Calculate timestamps: week 1 starts 18 weeks ago from now
    now = _time.time()
    week_seconds = 7 * 24 * 3600
    semester_start = now - (18 * week_seconds)

    total_seeded = 0
    for week_data in SEMESTER_WEEKS:
        week_base_ts = semester_start + (week_data.week - 1) * week_seconds
        for i, (fact_text, category) in enumerate(week_data.facts):
            _memory.add(SEMESTER_STUDENT_ID, fact_text, category=category)
            total_seeded += 1

            # Backdate the timestamp via direct DB update
            # Each fact within a week is spaced ~1 day apart
            target_ts = week_base_ts + i * 24 * 3600
            conn = _memory._store._get_conn()
            conn.execute(
                "UPDATE facts SET created_at = ?, updated_at = ? "
                "WHERE user_id = ? AND fact_text = ?",
                (target_ts, target_ts, SEMESTER_STUDENT_ID, fact_text),
            )
            conn.commit()

    actual_total = len(_memory.list(SEMESTER_STUDENT_ID))

    return SemesterDemoResponse(
        status="seeded",
        student_id=SEMESTER_STUDENT_ID,
        weeks_seeded=len(SEMESTER_WEEKS),
        total_memories=actual_total,
    )


# ------------------------------------------------------------------
# Export / Import endpoints
# ------------------------------------------------------------------


class ExportResponse(BaseModel):
    moodle_user_id: int
    record_count: int
    bundle: dict[str, Any]


class ExportAllResponse(BaseModel):
    students_exported: int
    total_records: int
    bundles: list[dict[str, Any]]


class ImportResponse(BaseModel):
    status: str
    user_id: str
    records_imported: int


@app.get("/export/student/{moodle_user_id}", response_model=ExportResponse)
async def export_student(moodle_user_id: int) -> ExportResponse:
    """Export a student's memory as a portable MemoryBundle JSON."""
    assistant = get_assistant()
    mem = assistant.memory
    user_id = f"moodle:{moodle_user_id}"

    bundle = mem.export(user_id)
    return ExportResponse(
        moodle_user_id=moodle_user_id,
        record_count=len(bundle.records),
        bundle=bundle.to_dict(),
    )


@app.get("/export/all", response_model=ExportAllResponse)
async def export_all() -> ExportAllResponse:
    """Export all students' memories as portable MemoryBundle JSONs."""
    assistant = get_assistant()
    mem = assistant.memory

    bundles: list[dict[str, Any]] = []
    total_records = 0
    for uid in mem.list_users():
        if not uid.startswith("moodle:"):
            continue
        bundle = mem.export(uid)
        bundles.append(bundle.to_dict())
        total_records += len(bundle.records)

    return ExportAllResponse(
        students_exported=len(bundles),
        total_records=total_records,
        bundles=bundles,
    )


@app.post("/import", response_model=ImportResponse)
async def import_memory(file: UploadFile) -> ImportResponse:
    """Import a student's memory from a MemoryBundle JSON file.

    Accepts a JSON file produced by the export endpoint.
    Merges with existing memories (does not overwrite by default).
    """
    assistant = get_assistant()
    mem = assistant.memory

    try:
        content = await file.read()
        data = json.loads(content)
        bundle = MemoryBundle.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid bundle JSON: {e}")

    count = mem.import_bundle(bundle)
    return ImportResponse(
        status="imported",
        user_id=bundle.user_id,
        records_imported=count,
    )


# ------------------------------------------------------------------
# Static files & SPA
# ------------------------------------------------------------------


@app.get("/")
async def index() -> FileResponse:
    """Serve the student chat UI."""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/teacher")
async def teacher_dashboard() -> FileResponse:
    """Serve the teacher dashboard UI."""
    return FileResponse(_STATIC_DIR / "teacher.html")


@app.get("/demo")
async def demo_walkthrough() -> FileResponse:
    """Serve the demo walkthrough page."""
    return FileResponse(_STATIC_DIR / "demo.html")


@app.get("/semester")
async def semester_page() -> FileResponse:
    """Serve the semester demo timeline page."""
    return FileResponse(_STATIC_DIR / "semester.html")


# LTI 1.3 integration
app.include_router(lti_router)

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
