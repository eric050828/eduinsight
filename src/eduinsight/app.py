"""FastAPI application for EduInsight.

Provides REST endpoints for:
- Student chat interactions (with memory context)
- Moodle data retrieval (courses, assignments, grades)
- Health check
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from litemem import Memory
from litemem.portable import MemoryBundle
from pydantic import BaseModel

from .analytics import (
    analyze_class,
    analyze_student,
    assess_risk,
    learning_trajectory,
)
from .assistant import LearningAssistant
from .attendance import AttendanceManager, GPSLocation
from .config import settings
from .documents import parse_document
from .grades import GradeManager
from .interaction import InteractionManager
from .lectures import LectureManager
from .live_quiz import (
    QuizSessionManager,
    QuizSessionQuestion,
    SessionStatus,
)
from .llm import ClaudeCLIClient, LLMClient, resolve_llm_config
from .lti import router as lti_router
from .moodle import MoodleClient
from .quiz import QuizGenerator
from .rag import CourseRAG
from .report import ReportGenerator

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Shared state (initialized at startup)
# ------------------------------------------------------------------
_memory: Memory | None = None
_assistant: LearningAssistant | None = None
_llm: LLMClient | None = None
_rag: CourseRAG | None = None
_quiz: QuizGenerator | None = None
_quiz_manager: QuizSessionManager = QuizSessionManager()
_interaction: InteractionManager = InteractionManager()
_attendance: AttendanceManager = AttendanceManager()
_grades: GradeManager = GradeManager()
_lectures: LectureManager | None = None


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
    global _memory, _assistant, _llm, _lectures
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
            logger.warning(
                "No LLM API key or claude CLI found. /chat will return memory context only."
            )
            _llm = None

    _assistant = LearningAssistant(_memory, llm=_llm)
    _rag = CourseRAG(_memory)
    _quiz = QuizGenerator(_rag, _llm) if _llm is not None else None
    _lectures = LectureManager(_memory)
    yield

    logger.info("Shutting down EduInsight")
    if _llm is not None:
        await _llm.__aexit__(None, None, None)
        _llm = None
    _memory = None
    _assistant = None
    _rag = None
    _quiz = None
    _lectures = None


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
    course_id: str = ""  # Optional: include RAG context from course materials


class ChatResponse(BaseModel):
    reply: str
    memory_context: list[str]
    material_context: list[str] = []  # RAG references from course materials


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
async def health() -> dict[str, Any]:
    llm_name = "None"
    if _llm is not None:
        llm_name = getattr(_llm, "model", None) or type(_llm).__name__
    result: dict[str, Any] = {"status": "ok", "version": "0.1.0", "llm_provider": llm_name}
    if _memory is not None:
        try:
            stats = _memory.detailed_stats()
            result["memory_db"] = settings.memory_db_path
            result["total_users"] = stats.total_users
            result["total_facts"] = stats.total_facts
        except Exception:
            result["memory_db"] = "error"
    return result


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Student sends a message; assistant responds with memory-augmented AI answer.

    If course_id is provided, retrieves relevant course materials (RAG)
    and includes them in the prompt context alongside student memories.
    """
    assistant = get_assistant()

    uid = f"moodle:{req.moodle_user_id}"
    session_id = f"chat_{int(time.time() * 1000)}"

    # RAG: retrieve relevant course materials if course_id provided
    material_refs: list[str] = []
    rag_context = ""
    if req.course_id and _rag is not None:
        rag_results = _rag.search(req.course_id, req.message, top_k=5)
        material_refs = [
            f"[{r.source} p.{r.page}] {r.text}" if r.page else f"[{r.source}] {r.text}"
            for r in rag_results
        ]
        rag_context = _rag.get_context_for_prompt(req.course_id, req.message)

    if assistant._llm is not None:
        # Full AI answer with memory + RAG context
        response = await assistant.answer(
            req.moodle_user_id, req.message, topic=req.topic,
            material_context=rag_context,
        )
        # Store conversation messages for history retrieval
        _memory._store.store_message(uid, req.message, session_id=session_id, role="user")
        _memory._store.store_message(
            uid, response.answer, session_id=session_id, role="assistant"
        )
        return ChatResponse(
            reply=response.answer,
            memory_context=response.memory_context,
            material_context=material_refs,
        )

    # Fallback: no LLM configured, return context only
    context_texts = assistant.get_student_context(req.moodle_user_id, req.message)
    assistant.record_question(req.moodle_user_id, req.message, topic=req.topic)
    fallback_reply = (
        "[No LLM configured] Memory context retrieved."
        " Set GEMINI_API_KEY to enable AI answers."
    )
    # Store even fallback conversations for history
    _memory._store.store_message(uid, req.message, session_id=session_id, role="user")
    _memory._store.store_message(uid, fallback_reply, session_id=session_id, role="assistant")
    return ChatResponse(
        reply=fallback_reply,
        memory_context=context_texts,
        material_context=material_refs,
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


@app.get("/moodle/grades/{course_id}/{moodle_user_id}")
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


@app.get("/student/{moodle_user_id}/conversations")
async def student_conversations(moodle_user_id: int, limit: int = 50) -> dict[str, Any]:
    """Get past conversation history for a student from the messages table."""
    uid = f"moodle:{moodle_user_id}"
    try:
        rows = _memory._store.get_messages(uid)
    except Exception:
        return {"moodle_user_id": moodle_user_id, "total_conversations": 0, "conversations": []}

    # Group by session
    sessions: dict[str, list[dict[str, Any]]] = {}
    for msg in rows:
        sid = msg.get("session_id", "")
        if sid not in sessions:
            sessions[sid] = []
        sessions[sid].append({
            "role": msg["role"],
            "content": msg["content"],
            "created_at": msg["created_at"],
        })

    # Sort sessions by earliest message, most recent first
    sorted_sessions = []
    for sid, msgs in sessions.items():
        msgs.sort(key=lambda m: m["created_at"])
        sorted_sessions.append({
            "session_id": sid,
            "timestamp": msgs[0]["created_at"],
            "messages": msgs,
        })
    sorted_sessions.sort(key=lambda s: s["timestamp"], reverse=True)

    # Apply limit to total messages
    total_msgs = 0
    limited_sessions = []
    for sess in sorted_sessions:
        if total_msgs >= limit:
            break
        remaining = limit - total_msgs
        if len(sess["messages"]) > remaining:
            sess["messages"] = sess["messages"][:remaining]
        total_msgs += len(sess["messages"])
        limited_sessions.append(sess)

    return {
        "moodle_user_id": moodle_user_id,
        "total_conversations": len(limited_sessions),
        "conversations": limited_sessions,
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


class RiskFactorResponse(BaseModel):
    label: str
    severity: str
    detail: str = ""


class StudentRiskResponse(BaseModel):
    moodle_user_id: int
    risk_level: str
    persistence_score: int
    factors: list[RiskFactorResponse]
    days_since_last_activity: int | None = None


@app.get("/analytics/student/{moodle_user_id}/risk", response_model=StudentRiskResponse)
async def get_student_risk(moodle_user_id: int) -> StudentRiskResponse:
    """Assess a student's risk level based on their learning activity patterns."""
    assistant = get_assistant()
    risk = assess_risk(assistant.memory, moodle_user_id)
    return StudentRiskResponse(
        moodle_user_id=risk.moodle_user_id,
        risk_level=risk.risk_level,
        persistence_score=risk.persistence_score,
        factors=[
            RiskFactorResponse(label=f.label, severity=f.severity, detail=f.detail)
            for f in risk.factors
        ],
        days_since_last_activity=risk.days_since_last_activity,
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
# Course Materials (RAG) endpoints
# ------------------------------------------------------------------


class MaterialUploadResponse(BaseModel):
    status: str
    filename: str
    course_id: str
    chunks_indexed: int
    total_pages: int


class MaterialListResponse(BaseModel):
    course_id: str
    documents: list[str]


class MaterialDeleteResponse(BaseModel):
    status: str
    filename: str
    chunks_removed: int


@app.post(
    "/courses/{course_id}/materials",
    response_model=MaterialUploadResponse,
)
async def upload_material(course_id: str, file: UploadFile) -> MaterialUploadResponse:
    """Upload a course document (PDF/PPTX) for RAG-powered Q&A.

    The document is parsed, chunked, and indexed into Lite-Mem so that
    student questions can reference course materials in their answers.
    """
    if _rag is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".pptx"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: .pdf, .pptx",
        )

    # Save to a temp file for parsing
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        doc = parse_document(tmp_path)
        # Use the original filename instead of the temp path
        doc.filename = file.filename
        for chunk in doc.chunks:
            chunk.source = file.filename
        chunks_indexed = _rag.index_document(course_id, doc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return MaterialUploadResponse(
        status="indexed",
        filename=file.filename,
        course_id=course_id,
        chunks_indexed=chunks_indexed,
        total_pages=doc.total_pages,
    )


@app.get("/courses/{course_id}/materials", response_model=MaterialListResponse)
async def list_materials(course_id: str) -> MaterialListResponse:
    """List all indexed documents for a course."""
    if _rag is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")
    docs = _rag.list_documents(course_id)
    return MaterialListResponse(course_id=course_id, documents=docs)


@app.delete(
    "/courses/{course_id}/materials/{filename}",
    response_model=MaterialDeleteResponse,
)
async def delete_material(course_id: str, filename: str) -> MaterialDeleteResponse:
    """Remove a document's indexed chunks from the course."""
    if _rag is None:
        raise HTTPException(status_code=503, detail="RAG not initialized")
    removed = _rag.remove_document(course_id, filename)
    return MaterialDeleteResponse(
        status="removed" if removed > 0 else "not_found",
        filename=filename,
        chunks_removed=removed,
    )


# ------------------------------------------------------------------
# Quiz generation endpoints
# ------------------------------------------------------------------


class QuizGenerateRequest(BaseModel):
    topic: str = ""
    num_questions: int = 5


class QuizQuestionResponse(BaseModel):
    question: str
    options: dict[str, str]
    answer: str
    explanation: str
    source: str = ""


class QuizGenerateResponse(BaseModel):
    course_id: str
    topic: str
    questions: list[QuizQuestionResponse]
    chunks_used: int


@app.post(
    "/courses/{course_id}/quiz/generate",
    response_model=QuizGenerateResponse,
)
async def generate_quiz(course_id: str, req: QuizGenerateRequest) -> QuizGenerateResponse:
    """Generate multiple-choice quiz questions from course materials using AI.

    Retrieves relevant document chunks via RAG, then prompts the LLM
    to create quiz questions based on the content.
    """
    if _quiz is None:
        raise HTTPException(
            status_code=503,
            detail="Quiz generation requires an LLM. Set GEMINI_API_KEY or install claude CLI.",
        )

    try:
        result = await _quiz.generate(
            course_id,
            topic=req.topic,
            num_questions=req.num_questions,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return QuizGenerateResponse(
        course_id=result.course_id,
        topic=result.topic,
        questions=[
            QuizQuestionResponse(
                question=q.question,
                options=q.options,
                answer=q.answer,
                explanation=q.explanation,
                source=q.source,
            )
            for q in result.questions
        ],
        chunks_used=result.chunks_used,
    )


# ------------------------------------------------------------------
# Live quiz session endpoints
# ------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    course_id: str
    title: str = ""
    questions: list[QuizQuestionResponse]


class CreateSessionResponse(BaseModel):
    session_id: str
    course_id: str
    title: str
    status: str
    question_count: int


class SubmitAnswerRequest(BaseModel):
    student_id: int
    question_idx: int
    selected: str  # "A", "B", "C", or "D"


class SubmitAnswerResponse(BaseModel):
    is_correct: bool
    correct_answer: str


class QuestionStatsResponse(BaseModel):
    question_idx: int
    total_answers: int
    correct_count: int
    correct_rate: float
    option_distribution: dict[str, int]


class SessionStatsResponse(BaseModel):
    session_id: str
    status: str
    total_students: int
    total_questions: int
    overall_correct_rate: float
    questions: list[QuestionStatsResponse]


class SessionInfoResponse(BaseModel):
    session_id: str
    course_id: str
    title: str
    status: str
    question_count: int
    total_students: int


@app.post("/quiz/sessions", response_model=CreateSessionResponse)
async def create_quiz_session(req: CreateSessionRequest) -> CreateSessionResponse:
    """Create a live quiz session from a set of questions.

    Teacher creates a session; students can join once it's activated.
    """
    questions = [
        QuizSessionQuestion(
            question=q.question,
            options=q.options,
            answer=q.answer,
            explanation=q.explanation,
            source=q.source,
        )
        for q in req.questions
    ]
    try:
        session = _quiz_manager.create_session(
            req.course_id, questions, teacher_id=0, title=req.title
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return CreateSessionResponse(
        session_id=session.session_id,
        course_id=session.course_id,
        title=session.title,
        status=session.status.value,
        question_count=len(session.questions),
    )


@app.post("/quiz/sessions/{session_id}/activate", response_model=SessionInfoResponse)
async def activate_quiz_session(session_id: str) -> SessionInfoResponse:
    """Activate a session so students can submit answers."""
    try:
        session = _quiz_manager.activate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return SessionInfoResponse(
        session_id=session.session_id,
        course_id=session.course_id,
        title=session.title,
        status=session.status.value,
        question_count=len(session.questions),
        total_students=len(session.get_student_ids()),
    )


@app.post("/quiz/sessions/{session_id}/close", response_model=SessionInfoResponse)
async def close_quiz_session(session_id: str) -> SessionInfoResponse:
    """Close a session (no more answers accepted)."""
    try:
        session = _quiz_manager.close_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionInfoResponse(
        session_id=session.session_id,
        course_id=session.course_id,
        title=session.title,
        status=session.status.value,
        question_count=len(session.questions),
        total_students=len(session.get_student_ids()),
    )


@app.get("/quiz/sessions/{session_id}", response_model=SessionInfoResponse)
async def get_quiz_session(session_id: str) -> SessionInfoResponse:
    """Get session info (without revealing correct answers)."""
    try:
        session = _quiz_manager.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionInfoResponse(
        session_id=session.session_id,
        course_id=session.course_id,
        title=session.title,
        status=session.status.value,
        question_count=len(session.questions),
        total_students=len(session.get_student_ids()),
    )


@app.get("/quiz/sessions/{session_id}/questions")
async def get_session_questions(session_id: str) -> list[dict]:
    """Get questions for students (without correct answers)."""
    try:
        session = _quiz_manager.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status == SessionStatus.WAITING:
        raise HTTPException(status_code=403, detail="Session not yet active")

    return [
        {
            "question_idx": idx,
            "question": q.question,
            "options": q.options,
        }
        for idx, q in enumerate(session.questions)
    ]


@app.post("/quiz/sessions/{session_id}/answer", response_model=SubmitAnswerResponse)
async def submit_quiz_answer(
    session_id: str, req: SubmitAnswerRequest
) -> SubmitAnswerResponse:
    """Submit a student's answer to a question."""
    try:
        answer = _quiz_manager.submit_answer(
            session_id,
            student_id=req.student_id,
            question_idx=req.question_idx,
            selected=req.selected,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Return whether correct + the correct answer (immediate feedback)
    session = _quiz_manager.get_session(session_id)
    correct_answer = session.questions[req.question_idx].answer
    return SubmitAnswerResponse(
        is_correct=answer.is_correct,
        correct_answer=correct_answer,
    )


@app.get("/quiz/sessions/{session_id}/stats", response_model=SessionStatsResponse)
async def get_quiz_stats(session_id: str) -> SessionStatsResponse:
    """Get real-time statistics for a quiz session.

    Returns per-question correct rate and option distribution.
    """
    try:
        stats = _quiz_manager.get_stats(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionStatsResponse(
        session_id=stats.session_id,
        status=stats.status.value,
        total_students=stats.total_students,
        total_questions=stats.total_questions,
        overall_correct_rate=stats.overall_correct_rate,
        questions=[
            QuestionStatsResponse(
                question_idx=qs.question_idx,
                total_answers=qs.total_answers,
                correct_count=qs.correct_count,
                correct_rate=qs.correct_rate,
                option_distribution=qs.option_distribution,
            )
            for qs in stats.questions
        ],
    )


@app.get("/quiz/sessions")
async def list_quiz_sessions(course_id: str | None = None) -> list[SessionInfoResponse]:
    """List quiz sessions, optionally filtered by course."""
    sessions = _quiz_manager.list_sessions(course_id)
    return [
        SessionInfoResponse(
            session_id=s.session_id,
            course_id=s.course_id,
            title=s.title,
            status=s.status.value,
            question_count=len(s.questions),
            total_students=len(s.get_student_ids()),
        )
        for s in sessions
    ]


# ------------------------------------------------------------------
# Interaction endpoints (polls, anonymous questions, danmaku)
# ------------------------------------------------------------------


class CreatePollRequest(BaseModel):
    course_id: str
    title: str
    options: list[str]


class PollResponse(BaseModel):
    poll_id: str
    course_id: str
    title: str
    status: str
    options: list[str]


class PollStatsResponse(BaseModel):
    poll_id: str
    title: str
    status: str
    options: list[str]
    total_votes: int
    distribution: list[int]


class VoteRequest(BaseModel):
    student_id: int
    option_idx: int


class PostQuestionRequest(BaseModel):
    course_id: str
    student_id: int
    text: str


class AnonQuestionResponse(BaseModel):
    question_id: str
    text: str
    upvote_count: int
    resolved: bool
    created_at: float


class UpvoteRequest(BaseModel):
    student_id: int


class PostDanmakuRequest(BaseModel):
    course_id: str
    student_id: int
    text: str


class DanmakuResponse(BaseModel):
    message_id: str
    text: str
    created_at: float


# ── Polls ─────────────────────────────────────────────────────────


@app.post("/interaction/polls", response_model=PollResponse)
async def create_poll(req: CreatePollRequest) -> PollResponse:
    """Create a new classroom poll."""
    try:
        poll = _interaction.create_poll(
            req.course_id, teacher_id=0, title=req.title, options=req.options
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PollResponse(
        poll_id=poll.poll_id,
        course_id=poll.course_id,
        title=poll.title,
        status=poll.status.value,
        options=poll.options,
    )


@app.post("/interaction/polls/{poll_id}/activate", response_model=PollResponse)
async def activate_poll(poll_id: str) -> PollResponse:
    """Open a poll for voting."""
    try:
        poll = _interaction.activate_poll(poll_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Poll not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PollResponse(
        poll_id=poll.poll_id,
        course_id=poll.course_id,
        title=poll.title,
        status=poll.status.value,
        options=poll.options,
    )


@app.post("/interaction/polls/{poll_id}/close", response_model=PollResponse)
async def close_poll(poll_id: str) -> PollResponse:
    """Close a poll (no more votes accepted)."""
    try:
        poll = _interaction.close_poll(poll_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Poll not found")
    return PollResponse(
        poll_id=poll.poll_id,
        course_id=poll.course_id,
        title=poll.title,
        status=poll.status.value,
        options=poll.options,
    )


@app.post("/interaction/polls/{poll_id}/vote")
async def vote_poll(poll_id: str, req: VoteRequest) -> dict[str, str]:
    """Cast or change a vote on a poll."""
    try:
        _interaction.vote(poll_id, student_id=req.student_id, option_idx=req.option_idx)
    except KeyError:
        raise HTTPException(status_code=404, detail="Poll not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "voted"}


@app.get("/interaction/polls/{poll_id}/stats", response_model=PollStatsResponse)
async def poll_stats(poll_id: str) -> PollStatsResponse:
    """Get real-time poll results."""
    try:
        stats = _interaction.poll_stats(poll_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Poll not found")
    return PollStatsResponse(
        poll_id=stats.poll_id,
        title=stats.title,
        status=stats.status.value,
        options=stats.options,
        total_votes=stats.total_votes,
        distribution=stats.distribution,
    )


@app.get("/interaction/polls")
async def list_polls(course_id: str | None = None) -> list[PollResponse]:
    """List polls, optionally filtered by course."""
    polls = _interaction.list_polls(course_id)
    return [
        PollResponse(
            poll_id=p.poll_id,
            course_id=p.course_id,
            title=p.title,
            status=p.status.value,
            options=p.options,
        )
        for p in polls
    ]


# ── Anonymous Questions ───────────────────────────────────────────


@app.post("/interaction/questions", response_model=AnonQuestionResponse)
async def post_question(req: PostQuestionRequest) -> AnonQuestionResponse:
    """Post an anonymous question (student identity hidden in response)."""
    try:
        q = _interaction.post_question(
            req.course_id, text=req.text, student_id=req.student_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AnonQuestionResponse(
        question_id=q.question_id,
        text=q.text,
        upvote_count=q.upvote_count,
        resolved=q.resolved,
        created_at=q.created_at,
    )


@app.post("/interaction/questions/{question_id}/upvote")
async def upvote_question(question_id: str, req: UpvoteRequest) -> dict[str, int]:
    """Upvote an anonymous question."""
    try:
        count = _interaction.upvote_question(question_id, student_id=req.student_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"upvote_count": count}


@app.post("/interaction/questions/{question_id}/resolve", response_model=AnonQuestionResponse)
async def resolve_question(question_id: str) -> AnonQuestionResponse:
    """Mark a question as resolved (teacher action)."""
    try:
        q = _interaction.resolve_question(question_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Question not found")
    return AnonQuestionResponse(
        question_id=q.question_id,
        text=q.text,
        upvote_count=q.upvote_count,
        resolved=q.resolved,
        created_at=q.created_at,
    )


@app.get("/interaction/questions")
async def list_questions(
    course_id: str, include_resolved: bool = True
) -> list[AnonQuestionResponse]:
    """List anonymous questions for a course, sorted by upvotes."""
    questions = _interaction.list_questions(course_id, include_resolved=include_resolved)
    return [
        AnonQuestionResponse(
            question_id=q.question_id,
            text=q.text,
            upvote_count=q.upvote_count,
            resolved=q.resolved,
            created_at=q.created_at,
        )
        for q in questions
    ]


# ── Danmaku (Text Wall) ──────────────────────────────────────────


@app.post("/interaction/danmaku", response_model=DanmakuResponse)
async def post_danmaku(req: PostDanmakuRequest) -> DanmakuResponse:
    """Post a danmaku (text wall) message."""
    try:
        msg = _interaction.post_danmaku(
            req.course_id, text=req.text, student_id=req.student_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DanmakuResponse(
        message_id=msg.message_id,
        text=msg.text,
        created_at=msg.created_at,
    )


@app.get("/interaction/danmaku")
async def get_danmaku(
    course_id: str, limit: int = 50, since: float | None = None
) -> list[DanmakuResponse]:
    """Get recent danmaku messages for a course."""
    messages = _interaction.get_danmaku(course_id, limit=limit, since=since)
    return [
        DanmakuResponse(
            message_id=m.message_id,
            text=m.text,
            created_at=m.created_at,
        )
        for m in messages
    ]


# ------------------------------------------------------------------
# Lecture recording endpoints
# ------------------------------------------------------------------


class LectureUploadResponse(BaseModel):
    id: str
    course_id: str
    title: str
    filename: str
    duration: float
    language: str
    provider: str
    summary: str
    chunks_indexed: int
    segment_count: int


class LectureInfoResponse(BaseModel):
    id: str
    course_id: str
    title: str
    filename: str
    duration: float
    language: str
    provider: str
    summary: str
    chunks_indexed: int
    segment_count: int
    created_at: float


class LectureTranscriptResponse(BaseModel):
    id: str
    title: str
    text: str
    timestamped: str
    segments: list[dict]


@app.post("/lectures/{course_id}/upload", response_model=LectureUploadResponse)
async def upload_lecture(
    course_id: str,
    file: UploadFile,
    title: str = Form("Untitled Lecture"),
    language: str | None = Form(None),
) -> LectureUploadResponse:
    """Upload and process a lecture recording.

    Accepts audio files (mp3, wav, m4a, etc.). The file is transcribed,
    summarized, and indexed into the course RAG for student search.
    """
    if _lectures is None:
        raise HTTPException(status_code=503, detail="Lecture manager not initialized")

    import tempfile

    from .transcribe import SUPPORTED_FORMATS

    # Validate file extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {ext}. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}",
        )

    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        lecture = await _lectures.process_lecture(
            course_id, tmp_path, title, language=language,
        )
        return LectureUploadResponse(
            id=lecture.id,
            course_id=lecture.course_id,
            title=lecture.title,
            filename=file.filename or "unknown",
            duration=lecture.transcript.duration,
            language=lecture.transcript.language,
            provider=lecture.transcript.provider,
            summary=lecture.summary,
            chunks_indexed=lecture.chunks_indexed,
            segment_count=len(lecture.transcript.segments),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/lectures/{course_id}", response_model=list[LectureInfoResponse])
async def list_lectures(course_id: str) -> list[LectureInfoResponse]:
    """List all lectures for a course."""
    if _lectures is None:
        raise HTTPException(status_code=503, detail="Lecture manager not initialized")

    lectures = _lectures.list_lectures(course_id)
    return [
        LectureInfoResponse(
            id=lec.id,
            course_id=lec.course_id,
            title=lec.title,
            filename=lec.filename,
            duration=lec.transcript.duration,
            language=lec.transcript.language,
            provider=lec.transcript.provider,
            summary=lec.summary,
            chunks_indexed=lec.chunks_indexed,
            segment_count=len(lec.transcript.segments),
            created_at=lec.created_at,
        )
        for lec in lectures
    ]


@app.get("/lectures/{course_id}/{lecture_id}/transcript")
async def get_lecture_transcript(
    course_id: str, lecture_id: str,
) -> LectureTranscriptResponse:
    """Get the full transcript of a lecture."""
    if _lectures is None:
        raise HTTPException(status_code=503, detail="Lecture manager not initialized")

    lecture = _lectures.get_lecture(lecture_id)
    if not lecture or lecture.course_id != course_id:
        raise HTTPException(status_code=404, detail="Lecture not found")

    return LectureTranscriptResponse(
        id=lecture.id,
        title=lecture.title,
        text=lecture.transcript.text,
        timestamped=lecture.transcript_with_timestamps(),
        segments=[
            {"start": s.start, "end": s.end, "text": s.text}
            for s in lecture.transcript.segments
        ],
    )


@app.delete("/lectures/{course_id}/{lecture_id}")
async def delete_lecture(course_id: str, lecture_id: str) -> dict[str, bool]:
    """Delete a lecture and its indexed content."""
    if _lectures is None:
        raise HTTPException(status_code=503, detail="Lecture manager not initialized")

    lecture = _lectures.get_lecture(lecture_id)
    if not lecture or lecture.course_id != course_id:
        raise HTTPException(status_code=404, detail="Lecture not found")

    deleted = _lectures.delete_lecture(lecture_id)
    return {"deleted": deleted}


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
    5 demo students for walkthrough purposes.
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
            _memory.forget(uid)

    _memory = Memory(db_path, embedder=embedder)
    _assistant = LearningAssistant(_memory, llm=_llm)

    # Seed demo data (each fact is a (text, category) tuple)
    total_seeded = 0
    for user_id, facts in DEMO_STUDENTS.items():
        for fact_text, category in facts:
            _memory.add(user_id, fact_text, category=category)
        total_seeded += len(facts)

    # Seed sample conversation messages for chat history display
    from .demo_conversations import DEMO_CONVERSATIONS

    for user_id, convos in DEMO_CONVERSATIONS.items():
        for session_id, messages in convos:
            for role, content in messages:
                _memory._store.store_message(
                    user_id, content, session_id=session_id, role=role,
                )

    # Verify actual stored count (Lite-Mem dedup may reduce it)
    actual_total = 0
    for user_id in DEMO_STUDENTS:
        actual_total += len(_memory.list(user_id))

    if actual_total < total_seeded:
        logger.warning(
            "Demo seed: %d facts seeded but only %d survived (Lite-Mem dedup)",
            total_seeded, actual_total,
        )

    # Seed demo grade data
    from .demo_grades import seed_demo_grades

    seed_demo_grades(_grades)

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
        _memory.forget(SEMESTER_STUDENT_ID)

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


# ── Attendance ────────────────────────────────────────────────────


class CreateAttendanceSessionRequest(BaseModel):
    course_id: str
    title: str = ""
    late_threshold_sec: int = 600
    latitude: float | None = None
    longitude: float | None = None
    gps_radius_m: float = 200.0


class AttendanceSessionResponse(BaseModel):
    session_id: str
    course_id: str
    title: str
    status: str
    checkin_code: str
    created_at: float
    closed_at: float | None = None
    late_threshold_sec: int = 600
    has_gps: bool = False


class CheckinRequest(BaseModel):
    student_id: int
    code: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class CheckinResponse(BaseModel):
    student_id: int
    session_id: str
    status: str
    checked_in_at: float


class AttendanceStatsResponse(BaseModel):
    session_id: str
    title: str
    status: str
    total_checkins: int
    present_count: int
    late_count: int
    student_ids: list[int]


def _att_session_resp(s: Any) -> AttendanceSessionResponse:
    return AttendanceSessionResponse(
        session_id=s.session_id,
        course_id=s.course_id,
        title=s.title,
        status=s.status.value,
        checkin_code=s.checkin_code,
        created_at=s.created_at,
        closed_at=s.closed_at,
        late_threshold_sec=s.late_threshold_sec,
        has_gps=s.gps_location is not None,
    )


@app.post("/attendance/sessions", response_model=AttendanceSessionResponse)
async def create_attendance_session(
    req: CreateAttendanceSessionRequest,
) -> AttendanceSessionResponse:
    """Create and open an attendance session."""
    gps = None
    if req.latitude is not None and req.longitude is not None:
        gps = GPSLocation(latitude=req.latitude, longitude=req.longitude)
    session = _attendance.create_session(
        req.course_id,
        teacher_id=0,
        title=req.title,
        late_threshold_sec=req.late_threshold_sec,
        gps_location=gps,
        gps_radius_m=req.gps_radius_m,
    )
    return _att_session_resp(session)


@app.post("/attendance/sessions/{session_id}/close", response_model=AttendanceSessionResponse)
async def close_attendance_session(session_id: str) -> AttendanceSessionResponse:
    """Close an attendance session."""
    try:
        session = _attendance.close_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _att_session_resp(session)


@app.get("/attendance/sessions/{session_id}", response_model=AttendanceSessionResponse)
async def get_attendance_session(session_id: str) -> AttendanceSessionResponse:
    """Get session details."""
    try:
        session = _attendance.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return _att_session_resp(session)


@app.get("/attendance/sessions")
async def list_attendance_sessions(course_id: str | None = None) -> list[AttendanceSessionResponse]:
    """List attendance sessions."""
    sessions = _attendance.list_sessions(course_id)
    return [_att_session_resp(s) for s in sessions]


@app.post("/attendance/sessions/{session_id}/checkin", response_model=CheckinResponse)
async def attendance_checkin(session_id: str, req: CheckinRequest) -> CheckinResponse:
    """Student checks in to an attendance session."""
    gps = None
    if req.latitude is not None and req.longitude is not None:
        gps = GPSLocation(latitude=req.latitude, longitude=req.longitude)
    try:
        record = _attendance.checkin(
            session_id,
            student_id=req.student_id,
            code=req.code,
            gps_location=gps,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return CheckinResponse(
        student_id=record.student_id,
        session_id=record.session_id,
        status=record.status.value,
        checked_in_at=record.checked_in_at,
    )


@app.get("/attendance/sessions/{session_id}/records")
async def get_attendance_records(session_id: str) -> list[CheckinResponse]:
    """Get all check-in records for a session."""
    try:
        records = _attendance.get_records(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return [
        CheckinResponse(
            student_id=r.student_id,
            session_id=r.session_id,
            status=r.status.value,
            checked_in_at=r.checked_in_at,
        )
        for r in records
    ]


@app.get("/attendance/sessions/{session_id}/stats", response_model=AttendanceStatsResponse)
async def get_attendance_stats(session_id: str) -> AttendanceStatsResponse:
    """Get attendance statistics for a session."""
    try:
        stats = _attendance.session_stats(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return AttendanceStatsResponse(
        session_id=stats.session_id,
        title=stats.title,
        status=stats.status.value,
        total_checkins=stats.total_checkins,
        present_count=stats.present_count,
        late_count=stats.late_count,
        student_ids=stats.student_ids,
    )


@app.get("/attendance/student/{student_id}/history")
async def get_student_attendance_history(
    student_id: int, course_id: str | None = None
) -> list[dict]:
    """Get a student's attendance history."""
    return _attendance.student_history(student_id, course_id)


@app.post("/attendance/checkin-by-code", response_model=CheckinResponse)
async def checkin_by_code(req: CheckinRequest) -> CheckinResponse:
    """Student checks in using just a code (finds the matching session)."""
    if not req.code:
        raise HTTPException(status_code=400, detail="Check-in code is required")
    session = _attendance.find_session_by_code(req.code)
    if not session:
        raise HTTPException(status_code=404, detail="No open session with this code")
    gps = None
    if req.latitude is not None and req.longitude is not None:
        gps = GPSLocation(latitude=req.latitude, longitude=req.longitude)
    try:
        record = _attendance.checkin(
            session.session_id,
            student_id=req.student_id,
            code=req.code,
            gps_location=gps,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return CheckinResponse(
        student_id=record.student_id,
        session_id=record.session_id,
        status=record.status.value,
        checked_in_at=record.checked_in_at,
    )


# ------------------------------------------------------------------
# Grade management endpoints
# ------------------------------------------------------------------


class GradeCategoryRequest(BaseModel):
    name: str
    weight: float


class SetCategoriesRequest(BaseModel):
    categories: list[GradeCategoryRequest]


class GradeCategoryResponse(BaseModel):
    name: str
    weight: float


class RecordScoreRequest(BaseModel):
    student_id: int
    category: str
    item: str
    score: float
    total: float = 100.0


class ScoreResponse(BaseModel):
    record_id: str
    course_id: str
    student_id: int
    category: str
    item: str
    score: float
    total: float


class CategorySummaryResponse(BaseModel):
    category: str
    weight: float
    items: list[dict[str, Any]]
    average_pct: float
    weighted_contribution: float


class StudentGradeResponse(BaseModel):
    course_id: str
    student_id: int
    categories: list[CategorySummaryResponse]
    weighted_total: float
    rank: int | None = None
    total_students: int | None = None


class ClassOverviewResponse(BaseModel):
    course_id: str
    total_students: int
    mean: float
    median: float
    std_dev: float
    min_score: float
    max_score: float
    distribution: dict[str, int]
    rankings: list[dict[str, Any]]


class DeleteScoreRequest(BaseModel):
    student_id: int
    category: str
    item: str


@app.get("/grades/courses")
async def list_grade_courses() -> list[str]:
    """List all courses with grade categories configured."""
    return _grades.list_courses()


@app.post("/grades/{course_id}/categories", response_model=list[GradeCategoryResponse])
async def set_grade_categories(
    course_id: str, req: SetCategoriesRequest
) -> list[GradeCategoryResponse]:
    """Set grade categories and weights for a course."""
    try:
        cats = _grades.set_categories(
            course_id,
            [{"name": c.name, "weight": c.weight} for c in req.categories],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [GradeCategoryResponse(name=c.name, weight=c.weight) for c in cats]


@app.get("/grades/{course_id}/categories", response_model=list[GradeCategoryResponse])
async def get_grade_categories(course_id: str) -> list[GradeCategoryResponse]:
    """Get grade categories for a course."""
    try:
        cats = _grades.get_categories(course_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return [GradeCategoryResponse(name=c.name, weight=c.weight) for c in cats]


@app.post("/grades/{course_id}/scores", response_model=ScoreResponse)
async def record_score(course_id: str, req: RecordScoreRequest) -> ScoreResponse:
    """Record a score for a student."""
    try:
        rec = _grades.record_score(
            course_id,
            student_id=req.student_id,
            category=req.category,
            item=req.item,
            score=req.score,
            total=req.total,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ScoreResponse(
        record_id=rec.record_id,
        course_id=rec.course_id,
        student_id=rec.student_id,
        category=rec.category,
        item=rec.item,
        score=rec.score,
        total=rec.total,
    )


@app.get("/grades/{course_id}/scores")
async def get_scores(
    course_id: str,
    student_id: int | None = None,
    category: str | None = None,
) -> list[ScoreResponse]:
    """Get score records, optionally filtered."""
    records = _grades.get_scores(course_id, student_id=student_id, category=category)
    return [
        ScoreResponse(
            record_id=r.record_id,
            course_id=r.course_id,
            student_id=r.student_id,
            category=r.category,
            item=r.item,
            score=r.score,
            total=r.total,
        )
        for r in records
    ]


@app.delete("/grades/{course_id}/scores")
async def delete_score(course_id: str, req: DeleteScoreRequest) -> dict[str, bool]:
    """Delete a specific score record."""
    deleted = _grades.delete_score(
        course_id,
        student_id=req.student_id,
        category=req.category,
        item=req.item,
    )
    return {"deleted": deleted}


@app.get("/grades/{course_id}/student/{student_id}", response_model=StudentGradeResponse)
async def get_student_grades(
    course_id: str, student_id: int
) -> StudentGradeResponse:
    """Get weighted grade summary for a student."""
    try:
        summary = _grades.student_summary_with_rank(course_id, student_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return StudentGradeResponse(
        course_id=summary.course_id,
        student_id=summary.student_id,
        categories=[
            CategorySummaryResponse(
                category=c.category,
                weight=c.weight,
                items=c.items,
                average_pct=c.average_pct,
                weighted_contribution=c.weighted_contribution,
            )
            for c in summary.categories
        ],
        weighted_total=summary.weighted_total,
        rank=summary.rank,
        total_students=summary.total_students,
    )


@app.get("/grades/{course_id}/overview", response_model=ClassOverviewResponse)
async def get_class_overview(course_id: str) -> ClassOverviewResponse:
    """Get class-level grade statistics and rankings."""
    try:
        overview = _grades.class_overview(course_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ClassOverviewResponse(
        course_id=overview.course_id,
        total_students=overview.total_students,
        mean=overview.mean,
        median=overview.median,
        std_dev=overview.std_dev,
        min_score=overview.min_score,
        max_score=overview.max_score,
        distribution=overview.distribution,
        rankings=overview.rankings,
    )


# ------------------------------------------------------------------
# ------------------------------------------------------------------
# Teaching analytics reports
# ------------------------------------------------------------------


def _get_report_generator() -> ReportGenerator:
    if _memory is None:
        raise RuntimeError("Application not initialized")
    return ReportGenerator(
        memory=_memory,
        grades=_grades,
        attendance=_attendance,
        interaction=_interaction,
        quiz=_quiz_manager,
    )


@app.get("/reports/weekly/{course_id}")
async def weekly_report(course_id: str):
    """Generate a weekly teaching analytics report for a course."""
    gen = _get_report_generator()
    report = gen.weekly_report(course_id)
    return {
        "course_id": report.course_id,
        "total_students": report.total_students,
        "total_facts": report.total_facts,
        "avg_facts_per_student": round(report.avg_facts_per_student, 1),
        "common_struggles": [
            {"topic": t, "count": c} for t, c in report.common_struggles
        ],
        "high_risk_students": report.high_risk_students,
        "grade_mean": report.grade_mean,
        "grade_median": report.grade_median,
        "grade_std_dev": report.grade_std_dev,
        "grade_distribution": report.grade_distribution,
        "total_sessions": report.total_sessions,
        "avg_attendance_rate": report.avg_attendance_rate,
        "total_polls": report.total_polls,
        "total_questions": report.total_questions,
        "total_danmaku": report.total_danmaku,
        "total_quiz_sessions": report.total_quiz_sessions,
        "avg_quiz_score": report.avg_quiz_score,
        "students": [
            {
                "student_id": s.student_id,
                "fact_count": s.fact_count,
                "struggle_count": s.struggle_count,
                "risk_level": s.risk_level,
                "persistence_score": s.persistence_score,
                "weighted_grade": s.weighted_grade,
                "attendance_rate": s.attendance_rate,
            }
            for s in report.students
        ],
    }


@app.get("/reports/correlation/{course_id}")
async def ai_grade_correlation(course_id: str):
    """Analyze correlation between AI engagement and grades."""
    gen = _get_report_generator()
    result = gen.ai_grade_correlation(course_id)
    return {
        "course_id": result.course_id,
        "fact_grade_correlation": result.fact_grade_correlation,
        "persistence_grade_correlation": result.persistence_grade_correlation,
        "insight": result.insight,
        "points": [
            {
                "student_id": p.student_id,
                "fact_count": p.fact_count,
                "struggle_count": p.struggle_count,
                "persistence_score": p.persistence_score,
                "weighted_grade": p.weighted_grade,
            }
            for p in result.points
        ],
    }


@app.get("/reports/export/excel/{course_id}")
async def export_report_excel(course_id: str):
    """Export the weekly report as an Excel file (.xlsx)."""
    import io

    from fastapi.responses import Response
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    gen = _get_report_generator()
    report = gen.weekly_report(course_id)
    correlation = gen.ai_grade_correlation(course_id)

    wb = Workbook()

    # --- Sheet 1: Overview ---
    ws = wb.active
    ws.title = "教學總覽"
    header_font = Font(bold=True, size=12)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font_white = Font(bold=True, size=11, color="FFFFFF")

    ws.append(["EduInsight 教學分析報表"])
    ws["A1"].font = Font(bold=True, size=16)
    ws.append([f"課程代碼: {course_id}"])
    ws.append([])

    ws.append(["指標", "數值"])
    ws["A4"].font = header_font
    ws["B4"].font = header_font
    metrics = [
        ("學生人數", report.total_students),
        ("AI 互動記憶總數", report.total_facts),
        ("每人平均記憶", round(report.avg_facts_per_student, 1)),
        ("高風險學生數", len(report.high_risk_students)),
        ("成績平均", report.grade_mean or "N/A"),
        ("成績中位數", report.grade_median or "N/A"),
        ("成績標準差", report.grade_std_dev or "N/A"),
        ("出席次數", report.total_sessions),
        ("平均出席率", f"{report.avg_attendance_rate}%" if report.avg_attendance_rate else "N/A"),
        ("課堂投票數", report.total_polls),
        ("匿名提問數", report.total_questions),
        ("彈幕訊息數", report.total_danmaku),
        ("測驗場次", report.total_quiz_sessions),
        ("測驗平均分", f"{report.avg_quiz_score}%" if report.avg_quiz_score else "N/A"),
    ]
    for label, value in metrics:
        ws.append([label, value])

    # --- Sheet 2: Student details ---
    ws2 = wb.create_sheet("學生明細")
    headers = ["學生 ID", "記憶數", "困難數", "風險等級", "持續力", "加權成績", "出席率"]
    ws2.append(headers)
    for i, h in enumerate(headers, 1):
        cell = ws2.cell(row=1, column=i)
        cell.font = header_font_white
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    for s in report.students:
        ws2.append([
            s.student_id,
            s.fact_count,
            s.struggle_count,
            s.risk_level,
            s.persistence_score,
            s.weighted_grade if s.weighted_grade is not None else "N/A",
            f"{s.attendance_rate}%" if s.attendance_rate is not None else "N/A",
        ])

    # --- Sheet 3: Common struggles ---
    ws3 = wb.create_sheet("常見困難")
    ws3.append(["困難主題", "學生人數"])
    ws3["A1"].font = header_font
    ws3["B1"].font = header_font
    for topic, count in report.common_struggles:
        ws3.append([topic, count])

    # --- Sheet 4: AI-Grade Correlation ---
    ws4 = wb.create_sheet("AI互動-成績相關")
    ws4.append(["AI 互動與成績相關性分析"])
    ws4["A1"].font = Font(bold=True, size=14)
    ws4.append([])
    ws4.append([
        "互動量-成績相關係數",
        correlation.fact_grade_correlation or "N/A",
    ])
    ws4.append([
        "持續力-成績相關係數",
        correlation.persistence_grade_correlation or "N/A",
    ])
    ws4.append(["分析結論", correlation.insight])
    ws4.append([])
    ws4.append(["學生 ID", "記憶數", "困難數", "持續力分數", "加權成績"])
    row = ws4.max_row
    for i in range(1, 6):
        cell = ws4.cell(row=row, column=i)
        cell.font = header_font_white
        cell.fill = header_fill
    for p in correlation.points:
        ws4.append([
            p.student_id,
            p.fact_count,
            p.struggle_count,
            p.persistence_score,
            p.weighted_grade,
        ])

    # Auto-width columns
    for ws_sheet in [ws, ws2, ws3, ws4]:
        for col in ws_sheet.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws_sheet.column_dimensions[col_letter].width = min(max_len + 4, 40)

    # Save to bytes
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"eduinsight_report_{course_id}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Static files & SPA
# ------------------------------------------------------------------


@app.get("/")
async def index() -> FileResponse:
    """Serve the landing page."""
    return FileResponse(_STATIC_DIR / "landing.html")


@app.get("/student")
async def student_page() -> FileResponse:
    """Serve the student learning dashboard."""
    return FileResponse(_STATIC_DIR / "student.html")


@app.get("/teacher")
async def teacher_dashboard() -> FileResponse:
    """Serve the teacher analytics dashboard."""
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
