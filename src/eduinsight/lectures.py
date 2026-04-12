"""Lecture recording management — upload, transcribe, summarize, and index.

Manages the lifecycle of lecture recordings:
1. Upload audio file
2. Transcribe via Whisper API (Groq/OpenAI)
3. Generate summary via LLM
4. Index transcript into CourseRAG for student search

Storage: in-memory (single-process demo), same pattern as live_quiz.py.

Usage::

    from litemem import Memory
    manager = LectureManager(memory=Memory(":memory:"))
    lecture = await manager.process_lecture("CS101", "/path/to/lecture.mp3", "Week 3: Binary Trees")
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from litemem import Memory

from .documents import DocumentChunk, ParsedDocument
from .rag import CourseRAG
from .transcribe import (
    TranscriptResult,
    auto_transcriber,
)

logger = logging.getLogger(__name__)


@dataclass
class Lecture:
    """A processed lecture recording."""

    id: str
    course_id: str
    title: str
    filename: str  # original audio filename
    transcript: TranscriptResult
    summary: str = ""
    chunks_indexed: int = 0
    created_at: float = 0.0  # unix timestamp

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "course_id": self.course_id,
            "title": self.title,
            "filename": self.filename,
            "duration": self.transcript.duration,
            "language": self.transcript.language,
            "provider": self.transcript.provider,
            "summary": self.summary,
            "chunks_indexed": self.chunks_indexed,
            "segment_count": len(self.transcript.segments),
            "created_at": self.created_at,
        }

    def transcript_with_timestamps(self) -> str:
        """Format transcript with timestamps for display."""
        if not self.transcript.segments:
            return self.transcript.text
        lines = []
        for seg in self.transcript.segments:
            mm_start = int(seg.start // 60)
            ss_start = int(seg.start % 60)
            lines.append(f"[{mm_start:02d}:{ss_start:02d}] {seg.text}")
        return "\n".join(lines)


class LectureManager:
    """Manages lecture recordings: transcription, summarization, and indexing.

    In-memory store (single-process demo). Integrates with CourseRAG
    to make lecture content searchable by students.
    """

    def __init__(self, memory: Memory) -> None:
        self._memory = memory
        self._rag = CourseRAG(memory)
        self._lectures: dict[str, Lecture] = {}  # id -> Lecture
        self._transcriber = auto_transcriber()

    def set_transcriber(self, transcriber: object) -> None:
        """Override the transcriber (useful for testing)."""
        self._transcriber = transcriber  # type: ignore[assignment]

    async def process_lecture(
        self,
        course_id: str,
        audio_path: str | Path,
        title: str,
        *,
        language: str | None = None,
        generate_summary: bool = True,
    ) -> Lecture:
        """Full pipeline: transcribe → summarize → index into RAG.

        Args:
            course_id: Course identifier (e.g. "CS101").
            audio_path: Path to the audio file.
            title: Lecture title (e.g. "Week 3: Binary Trees").
            language: Optional language hint for transcription.
            generate_summary: Whether to generate LLM summary.

        Returns:
            Processed Lecture object.
        """
        path = Path(audio_path)
        lecture_id = f"lec_{uuid.uuid4().hex[:8]}"

        # Step 1: Transcribe
        logger.info("Transcribing %s for course %s...", path.name, course_id)
        transcript = await self._transcriber.transcribe(
            path, language=language,
        )
        logger.info(
            "Transcription complete: %d chars, %d segments, %.0fs duration",
            len(transcript.text), len(transcript.segments), transcript.duration,
        )

        # Step 2: Create lecture object
        lecture = Lecture(
            id=lecture_id,
            course_id=course_id,
            title=title,
            filename=path.name,
            transcript=transcript,
            created_at=time.time(),
        )

        # Step 3: Generate summary (if LLM available and requested)
        if generate_summary and transcript.text:
            lecture.summary = await self._generate_summary(transcript.text, title)

        # Step 4: Index transcript into RAG
        if transcript.text:
            lecture.chunks_indexed = self._index_transcript(
                course_id, lecture_id, title, transcript,
            )

        self._lectures[lecture_id] = lecture
        logger.info(
            "Lecture %s processed: %d chunks indexed, summary=%s",
            lecture_id, lecture.chunks_indexed, bool(lecture.summary),
        )
        return lecture

    def get_lecture(self, lecture_id: str) -> Lecture | None:
        return self._lectures.get(lecture_id)

    def list_lectures(self, course_id: str | None = None) -> list[Lecture]:
        lectures = list(self._lectures.values())
        if course_id:
            lectures = [lec for lec in lectures if lec.course_id == course_id]
        return sorted(lectures, key=lambda lec: lec.created_at, reverse=True)

    def delete_lecture(self, lecture_id: str) -> bool:
        lecture = self._lectures.pop(lecture_id, None)
        if not lecture:
            return False
        # Remove from RAG
        self._rag.remove_document(
            lecture.course_id, f"lecture:{lecture_id}",
        )
        return True

    def _index_transcript(
        self,
        course_id: str,
        lecture_id: str,
        title: str,
        transcript: TranscriptResult,
    ) -> int:
        """Index transcript segments into CourseRAG.

        Uses segment-level chunking when available, falling back
        to full-text chunking. Each chunk is tagged with lecture
        metadata for source attribution.
        """
        from .documents import chunk_text

        filename = f"lecture:{lecture_id}"
        chunks: list[DocumentChunk] = []

        if transcript.segments:
            # Group segments into ~500 char chunks
            current_text = ""
            current_start = 0.0
            seg_idx = 0

            for seg in transcript.segments:
                if current_text and len(current_text) + len(seg.text) > 450:
                    mm = int(current_start // 60)
                    ss = int(current_start % 60)
                    tagged = f"[{title} {mm:02d}:{ss:02d}] {current_text.strip()}"
                    chunks.append(DocumentChunk(
                        text=tagged, source=filename, page=None, chunk_index=seg_idx,
                    ))
                    seg_idx += 1
                    current_text = seg.text
                    current_start = seg.start
                else:
                    if not current_text:
                        current_start = seg.start
                    current_text += " " + seg.text

            # Last chunk
            if current_text.strip():
                mm = int(current_start // 60)
                ss = int(current_start % 60)
                tagged = f"[{title} {mm:02d}:{ss:02d}] {current_text.strip()}"
                chunks.append(DocumentChunk(
                    text=tagged, source=filename, page=None, chunk_index=seg_idx,
                ))
        else:
            # No segments — chunk the full text
            text_chunks = chunk_text(
                transcript.text, source=filename, chunk_size=500,
            )
            for c in text_chunks:
                c.text = f"[{title}] {c.text}"
            chunks = text_chunks

        # Store as ParsedDocument for CourseRAG
        doc = ParsedDocument(
            filename=filename,
            total_pages=len(chunks),
            chunks=chunks,
        )
        return self._rag.index_document(course_id, doc)

    async def _generate_summary(self, text: str, title: str) -> str:
        """Generate a lecture summary using the configured LLM."""
        try:
            from .llm import ClaudeCLIClient, LLMClient, resolve_llm_config

            # Truncate long transcripts for summary prompt
            max_chars = 6000
            truncated = text[:max_chars] + ("..." if len(text) > max_chars else "")

            system_prompt = (
                "You are a teaching assistant summarizing a lecture recording. "
                "Generate a concise summary in the same language as the transcript. "
                "Include: main topics covered, key concepts explained, and important examples. "
                "Use bullet points. Keep it under 300 words."
            )
            user_msg = f"Lecture: {title}\n\nTranscript:\n{truncated}"

            try:
                config = resolve_llm_config()
                async with LLMClient(config) as llm:
                    return await llm.chat(
                        user_msg,
                        system_prompt=system_prompt,
                        temperature=0.3,
                        max_tokens=600,
                    )
            except ValueError:
                # No API key — try Claude CLI
                async with ClaudeCLIClient() as llm:
                    return await llm.chat(
                        user_msg,
                        system_prompt=system_prompt,
                        max_tokens=600,
                    )
        except Exception as e:
            logger.warning("Failed to generate summary: %s", e)
            return ""
