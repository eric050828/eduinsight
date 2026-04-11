"""AI quiz generation from course materials.

Uses RAG to retrieve relevant document chunks, then prompts an LLM
to generate multiple-choice questions based on the content.

Usage::

    rag = CourseRAG(memory)
    gen = QuizGenerator(rag, llm)
    questions = await gen.generate("CS101", topic="binary search", num_questions=5)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from .rag import CourseRAG

logger = logging.getLogger(__name__)

QUIZ_SYSTEM_PROMPT = """\
You are a university-level quiz question generator.
Given course material excerpts, generate multiple-choice questions that test understanding.

Rules:
- Each question should have exactly 4 options (A, B, C, D)
- Exactly one option is correct
- Include a brief explanation of why the correct answer is right
- Questions should test comprehension, not just memorization
- Vary difficulty: mix recall, understanding, and application questions
- Write in the same language as the source material

Respond with ONLY a JSON array, no markdown fences, no extra text.
Each element must have these fields:
{
  "question": "the question text",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "answer": "A",
  "explanation": "why this is correct",
  "source": "filename and page if mentioned in the material"
}"""


@dataclass
class QuizQuestion:
    """A single multiple-choice quiz question."""

    question: str
    options: dict[str, str]  # {"A": "...", "B": "...", "C": "...", "D": "..."}
    answer: str  # "A", "B", "C", or "D"
    explanation: str
    source: str = ""  # e.g. "lecture03.pdf p.5"


@dataclass
class QuizResult:
    """Result of a quiz generation request."""

    course_id: str
    topic: str
    questions: list[QuizQuestion] = field(default_factory=list)
    chunks_used: int = 0


class QuizGenerator:
    """Generates quiz questions from course materials using RAG + LLM.

    Retrieves relevant document chunks via CourseRAG, then prompts the
    LLM to create multiple-choice questions based on that content.
    """

    def __init__(self, rag: CourseRAG, llm: object) -> None:
        self._rag = rag
        self._llm = llm  # LLMClient or ClaudeCLIClient (both have .chat())

    async def generate(
        self,
        course_id: str,
        *,
        topic: str = "",
        num_questions: int = 5,
        top_k: int = 8,
    ) -> QuizResult:
        """Generate quiz questions from course materials.

        Args:
            course_id: The course to generate questions for.
            topic: Optional topic focus (narrows RAG search).
            num_questions: Number of questions to generate (1-20).
            top_k: Number of material chunks to retrieve for context.

        Returns:
            QuizResult with generated questions.

        Raises:
            RuntimeError: If LLM call fails.
            ValueError: If no course materials are indexed.
        """
        num_questions = max(1, min(20, num_questions))

        # Build search query
        query = topic if topic else "key concepts and important topics"

        # Retrieve relevant material chunks
        results = self._rag.search(course_id, query, top_k=top_k)
        if not results:
            # Fallback: check if course has any materials at all
            docs = self._rag.list_documents(course_id)
            if not docs:
                raise ValueError(
                    f"No materials found for course '{course_id}'. "
                    "Upload documents first via POST /courses/{course_id}/materials"
                )
            # Materials exist but query didn't match — broaden search
            results = self._rag.search(course_id, docs[0], top_k=top_k)

        # Build context from chunks
        context_lines = []
        for i, r in enumerate(results, 1):
            page_info = f" (p.{r.page})" if r.page else ""
            context_lines.append(f"[{i}] {r.source}{page_info}: {r.text}")
        context = "\n".join(context_lines)

        # Build user prompt
        topic_instruction = f" Focus on the topic: {topic}." if topic else ""
        user_prompt = (
            f"Generate exactly {num_questions} multiple-choice questions "
            f"based on the following course material.{topic_instruction}\n\n"
            f"Course material:\n{context}"
        )

        # Call LLM
        raw = await self._llm.chat(
            user_prompt,
            system_prompt=QUIZ_SYSTEM_PROMPT,
            temperature=0.7,
            max_tokens=4096,
        )

        # Parse response
        questions = _parse_quiz_response(raw)

        return QuizResult(
            course_id=course_id,
            topic=topic,
            questions=questions,
            chunks_used=len(results),
        )


def _parse_quiz_response(raw: str) -> list[QuizQuestion]:
    """Parse LLM response into QuizQuestion objects.

    Handles common LLM output quirks: markdown fences, trailing commas, etc.
    """
    # Strip markdown code fences if present
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Try to find JSON array in the response
    # Sometimes LLM adds text before/after the JSON
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        text = match.group(0)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse quiz JSON, attempting cleanup: %s", text[:200])
        # Try removing trailing commas (common LLM mistake)
        cleaned = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Could not parse quiz response: %s", text[:500])
            return []

    if not isinstance(data, list):
        data = [data]

    questions = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            q = QuizQuestion(
                question=str(item.get("question", "")),
                options=item.get("options", {}),
                answer=str(item.get("answer", "")),
                explanation=str(item.get("explanation", "")),
                source=str(item.get("source", "")),
            )
            # Validate: must have question, 4 options, valid answer
            if (
                q.question
                and len(q.options) == 4
                and q.answer in q.options
            ):
                questions.append(q)
            else:
                logger.warning("Skipping malformed question: %s", item)
        except (TypeError, KeyError) as e:
            logger.warning("Skipping unparseable question: %s (%s)", item, e)

    return questions
