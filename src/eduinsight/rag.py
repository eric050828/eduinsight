"""RAG (Retrieval-Augmented Generation) module for course materials.

Uses Lite-Mem as the vector store — each course's documents are stored
under user_id = "course:{course_id}" with category = "course_material".
This reuses Lite-Mem's FTS5 + cosine hybrid search without any modification.

Usage::

    mem = Memory("eduinsight.db", embedder="auto")
    rag = CourseRAG(mem)

    # Index a document
    from .documents import parse_pdf
    doc = parse_pdf("lecture_notes.pdf")
    rag.index_document("CS101", doc)

    # Search for relevant content
    results = rag.search("CS101", "What is binary search?")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from litemem import Memory

from .documents import ParsedDocument, ParsedMarkdown

logger = logging.getLogger(__name__)


def _course_uid(course_id: str) -> str:
    """Convert a course ID to a Lite-Mem user_id string."""
    return f"course:{course_id}"


@dataclass
class RAGResult:
    """A search result from course materials."""

    text: str
    source: str  # filename
    page: int | None  # page/slide number (legacy)
    score: float
    heading: str = ""
    anchor_id: str = ""


class CourseRAG:
    """RAG engine for course materials, backed by Lite-Mem.

    Documents are chunked and stored as Lite-Mem facts under a
    course-specific namespace. Search uses Lite-Mem's hybrid
    FTS5 + cosine similarity when embeddings are enabled.
    """

    def __init__(self, memory: Memory) -> None:
        self._memory = memory

    def index_document(self, course_id: str, doc: ParsedDocument) -> int:
        """Index a legacy ParsedDocument (no markdown anchors)."""
        uid = _course_uid(course_id)
        indexed = 0
        for chunk in doc.chunks:
            page_tag = f"p.{chunk.page}" if chunk.page else "p.?"
            tagged_text = f"[{doc.filename} {page_tag}] {chunk.text}"
            self._memory.add(uid, tagged_text, category="course_material")
            indexed += 1
        logger.info(
            "Indexed %d chunks from %s into course %s (legacy mode)",
            indexed, doc.filename, course_id,
        )
        return indexed

    def index_markdown(self, course_id: str, doc: ParsedMarkdown) -> int:
        """Index a ParsedMarkdown's chunks with anchor metadata.

        Tagged text format: ``[filename §heading|anchor_id] body``
        — preserves heading + scroll anchor for citation jumping.
        """
        uid = _course_uid(course_id)
        indexed = 0
        for chunk in doc.chunks:
            heading = chunk.heading or "正文"
            anchor = chunk.anchor_id or "h-0"
            tagged_text = f"[{doc.filename} §{heading}|{anchor}] {chunk.text}"
            self._memory.add(uid, tagged_text, category="course_material")
            indexed += 1
        logger.info(
            "Indexed %d markdown chunks from %s into course %s",
            indexed, doc.filename, course_id,
        )
        return indexed

    def search(
        self,
        course_id: str,
        query: str,
        *,
        top_k: int = 5,
    ) -> list[RAGResult]:
        """Search course materials for relevant content.

        Uses Lite-Mem's hybrid search (FTS5 + cosine) to find
        the most relevant document chunks.

        Args:
            course_id: The course to search in.
            query: The search query (typically the student's question).
            top_k: Maximum number of results.

        Returns:
            List of RAGResult with text, source, page, and score.
        """
        uid = _course_uid(course_id)
        results = self._memory.query_detail(uid, query, top_k=top_k)

        rag_results: list[RAGResult] = []
        for r in results:
            source, page, heading, anchor, text = _parse_tagged_text(r.text)
            rag_results.append(
                RAGResult(
                    text=text, source=source, page=page, score=r.score,
                    heading=heading, anchor_id=anchor,
                )
            )

        return rag_results

    def list_documents(self, course_id: str) -> list[str]:
        """List all indexed document filenames for a course."""
        uid = _course_uid(course_id)
        all_facts = self._memory.list(uid, category="course_material")
        filenames: set[str] = set()
        for fact in all_facts:
            source, _, _, _, _ = _parse_tagged_text(fact)
            if source:
                filenames.add(source)
        return sorted(filenames)

    def remove_document(self, course_id: str, filename: str) -> int:
        """Remove all chunks from a specific document.

        Args:
            course_id: The course identifier.
            filename: The document filename to remove.

        Returns:
            Number of chunks removed.
        """
        uid = _course_uid(course_id)
        all_facts = self._memory.list(uid, category="course_material")
        removed = 0
        for fact in all_facts:
            source, _, _, _, _ = _parse_tagged_text(fact)
            if source == filename:
                self._memory.forget(uid)
                break

        # More efficient approach: get all, filter, forget all, re-add
        remaining = [f for f in all_facts if not f.startswith(f"[{filename} ")]
        if len(remaining) < len(all_facts):
            removed = len(all_facts) - len(remaining)
            self._memory.forget(uid)
            for fact in remaining:
                self._memory.add(uid, fact, category="course_material")
            logger.info("Removed %d chunks of %s from course %s", removed, filename, course_id)

        return removed

    def get_context_for_prompt(
        self,
        course_id: str,
        query: str,
        *,
        top_k: int = 5,
    ) -> str:
        """Get formatted context string for LLM prompt injection.

        Returns a formatted string suitable for including in the
        system or user prompt, with source citations.

        Args:
            course_id: The course to search in.
            query: The student's question.
            top_k: Maximum number of chunks to include.

        Returns:
            Formatted context string, or empty string if no results.
        """
        results = self.search(course_id, query, top_k=top_k)
        if not results:
            return ""

        lines = ["Course material references:"]
        for i, r in enumerate(results, 1):
            page_info = f" (p.{r.page})" if r.page else ""
            lines.append(f"  [{i}] {r.source}{page_info}: {r.text}")

        return "\n".join(lines)


def _parse_tagged_text(
    tagged: str,
) -> tuple[str, int | None, str, str, str]:
    """Parse a tagged fact text into (source, page, heading, anchor_id, text).

    Supports two formats:
        "[filename §heading|anchor_id] body"   # markdown pipeline
        "[filename p.N] body"                   # legacy PDF pipeline
    """
    import re

    # New markdown format
    m = re.match(r"^\[(.+?)\s+§(.+?)\|([\w\-]+)\]\s*(.*)$", tagged, re.DOTALL)
    if m:
        return m.group(1), None, m.group(2), m.group(3), m.group(4)

    # Legacy page format
    m = re.match(r"^\[(.+?)\s+p\.(\d+|\?)\]\s*(.*)$", tagged, re.DOTALL)
    if m:
        page_str = m.group(2)
        page = int(page_str) if page_str != "?" else None
        return m.group(1), page, "", "", m.group(3)

    return "", None, "", "", tagged
