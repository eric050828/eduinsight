"""Tests for RAG (Retrieval-Augmented Generation) module."""

from __future__ import annotations

import pytest
from litemem import Memory

from eduinsight.documents import DocumentChunk, ParsedDocument
from eduinsight.rag import CourseRAG, _parse_tagged_text

# ------------------------------------------------------------------
# Tag parsing tests
# ------------------------------------------------------------------


class TestParseTaggedText:
    def test_standard_format(self):
        source, page, text = _parse_tagged_text("[lecture.pdf p.5] Binary search explanation")
        assert source == "lecture.pdf"
        assert page == 5
        assert text == "Binary search explanation"

    def test_unknown_page(self):
        source, page, text = _parse_tagged_text("[notes.pdf p.?] Some content")
        assert source == "notes.pdf"
        assert page is None
        assert text == "Some content"

    def test_no_tag(self):
        source, page, text = _parse_tagged_text("Plain text without tag")
        assert source == ""
        assert page is None
        assert text == "Plain text without tag"

    def test_multiline_content(self):
        source, page, text = _parse_tagged_text("[doc.pdf p.1] Line one\nLine two")
        assert source == "doc.pdf"
        assert page == 1
        assert "Line one\nLine two" == text


# ------------------------------------------------------------------
# CourseRAG tests
# ------------------------------------------------------------------


class TestCourseRAG:
    @pytest.fixture
    def mem(self):
        return Memory(":memory:")

    @pytest.fixture
    def rag(self, mem):
        return CourseRAG(mem)

    @pytest.fixture
    def sample_doc(self):
        return ParsedDocument(
            filename="lecture01.pdf",
            total_pages=3,
            chunks=[
                DocumentChunk(
                    text="Binary search divides the array in half each step.",
                    source="lecture01.pdf",
                    page=1,
                    chunk_index=0,
                ),
                DocumentChunk(
                    text="Linked list nodes contain data and a pointer to the next node.",
                    source="lecture01.pdf",
                    page=2,
                    chunk_index=1,
                ),
                DocumentChunk(
                    text="Hash tables use a hash function to map keys to indices.",
                    source="lecture01.pdf",
                    page=3,
                    chunk_index=2,
                ),
            ],
        )

    def test_index_document(self, rag, sample_doc):
        count = rag.index_document("CS101", sample_doc)
        assert count == 3

    def test_search_returns_relevant_results(self, rag, sample_doc):
        rag.index_document("CS101", sample_doc)
        results = rag.search("CS101", "binary search")
        assert len(results) > 0
        # The most relevant result should mention binary search
        assert "binary search" in results[0].text.lower() or "Binary search" in results[0].text

    def test_search_returns_source_metadata(self, rag, sample_doc):
        rag.index_document("CS101", sample_doc)
        results = rag.search("CS101", "linked list")
        assert len(results) > 0
        # At least one result should have source info
        found = any(r.source == "lecture01.pdf" for r in results)
        assert found

    def test_search_empty_course(self, rag):
        results = rag.search("EMPTY", "anything")
        assert results == []

    def test_list_documents(self, rag, sample_doc):
        rag.index_document("CS101", sample_doc)
        docs = rag.list_documents("CS101")
        assert docs == ["lecture01.pdf"]

    def test_list_documents_multiple(self, rag, sample_doc):
        rag.index_document("CS101", sample_doc)
        # Add another doc
        doc2 = ParsedDocument(
            filename="lecture02.pdf",
            total_pages=1,
            chunks=[
                DocumentChunk(
                    text="Sorting algorithms comparison.",
                    source="lecture02.pdf",
                    page=1,
                    chunk_index=0,
                ),
            ],
        )
        rag.index_document("CS101", doc2)
        docs = rag.list_documents("CS101")
        assert docs == ["lecture01.pdf", "lecture02.pdf"]

    def test_list_documents_empty_course(self, rag):
        assert rag.list_documents("EMPTY") == []

    def test_remove_document(self, rag, sample_doc):
        rag.index_document("CS101", sample_doc)
        doc2 = ParsedDocument(
            filename="lecture02.pdf",
            total_pages=1,
            chunks=[
                DocumentChunk(
                    text="Trees and graphs.",
                    source="lecture02.pdf",
                    page=1,
                    chunk_index=0,
                ),
            ],
        )
        rag.index_document("CS101", doc2)

        removed = rag.remove_document("CS101", "lecture01.pdf")
        assert removed == 3
        # Only lecture02 should remain
        assert rag.list_documents("CS101") == ["lecture02.pdf"]

    def test_remove_nonexistent_document(self, rag, sample_doc):
        rag.index_document("CS101", sample_doc)
        removed = rag.remove_document("CS101", "nonexistent.pdf")
        assert removed == 0

    def test_get_context_for_prompt(self, rag, sample_doc):
        rag.index_document("CS101", sample_doc)
        context = rag.get_context_for_prompt("CS101", "hash table")
        assert "Course material references:" in context
        assert "lecture01.pdf" in context

    def test_get_context_for_prompt_empty(self, rag):
        context = rag.get_context_for_prompt("EMPTY", "anything")
        assert context == ""

    def test_courses_are_isolated(self, rag, sample_doc):
        rag.index_document("CS101", sample_doc)
        # Different course should have no results
        results = rag.search("CS202", "binary search")
        assert results == []

    def test_top_k_limits_results(self, rag):
        doc = ParsedDocument(
            filename="big.pdf",
            total_pages=10,
            chunks=[
                DocumentChunk(
                    text=f"Chunk {i} about data structures and algorithms.",
                    source="big.pdf",
                    page=i,
                    chunk_index=i,
                )
                for i in range(10)
            ],
        )
        rag.index_document("CS101", doc)
        results = rag.search("CS101", "data structures", top_k=3)
        assert len(results) <= 3
