"""FastAPI application for EduInsight.

Provides REST endpoints for:
- Student chat interactions (with memory context)
- Moodle data retrieval (courses, assignments, grades)
- Health check
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from litemem import Memory
from pydantic import BaseModel

from .assistant import LearningAssistant
from .config import settings
from .moodle import MoodleClient

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Shared state (initialized at startup)
# ------------------------------------------------------------------
_memory: Memory | None = None
_assistant: LearningAssistant | None = None


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
    global _memory, _assistant
    logger.info("Starting EduInsight with memory DB: %s", settings.memory_db_path)
    _memory = Memory(settings.memory_db_path)
    _assistant = LearningAssistant(_memory)
    yield
    logger.info("Shutting down EduInsight")
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


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Student sends a message; assistant responds with memory context.

    NOTE: Phase 1 returns memory context only. LLM-based answer
    generation will be added in Phase 2.
    """
    assistant = get_assistant()

    # Retrieve relevant memories
    context_texts = assistant.get_student_context(req.moodle_user_id, req.message)

    # Record the question
    assistant.record_question(req.moodle_user_id, req.message, topic=req.topic)

    # Phase 1: return context only, no LLM generation yet
    return ChatResponse(
        reply="[Phase 1] Memory context retrieved. LLM answer generation coming in Phase 2.",
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
