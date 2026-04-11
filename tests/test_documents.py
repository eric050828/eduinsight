"""Tests for document parsing and chunking."""

from __future__ import annotations

from pathlib import Path

import pytest

from eduinsight.documents import (
    chunk_text,
    parse_document,
    parse_pdf,
    parse_pptx,
)

# ------------------------------------------------------------------
# chunk_text tests
# ------------------------------------------------------------------


class TestChunkText:
    def test_empty_text_returns_empty(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_single_chunk(self):
        chunks = chunk_text("Hello world", chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0].text == "Hello world"
        assert chunks[0].chunk_index == 0

    def test_metadata_preserved(self):
        chunks = chunk_text("Hello", source="test.pdf", page=3, start_index=5)
        assert chunks[0].source == "test.pdf"
        assert chunks[0].page == 3
        assert chunks[0].chunk_index == 5

    def test_long_text_splits_into_multiple_chunks(self):
        # Create text with multiple paragraphs
        paragraphs = [f"Paragraph {i} with some content." for i in range(20)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1
        # All chunks should have content
        for c in chunks:
            assert len(c.text) > 0

    def test_chunk_indices_sequential(self):
        text = "\n\n".join([f"Para {i} " * 10 for i in range(10)])
        chunks = chunk_text(text, chunk_size=100)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_overlap_carries_context(self):
        para_a = "A" * 200
        para_b = "B" * 200
        text = f"{para_a}\n\n{para_b}"
        chunks = chunk_text(text, chunk_size=250, overlap=50)
        assert len(chunks) == 2
        # Second chunk should start with overlap from first
        assert chunks[1].text.startswith("A")

    def test_no_overlap(self):
        para_a = "A" * 200
        para_b = "B" * 200
        text = f"{para_a}\n\n{para_b}"
        chunks = chunk_text(text, chunk_size=250, overlap=0)
        assert len(chunks) == 2
        assert chunks[1].text.startswith("B")


# ------------------------------------------------------------------
# PDF parsing tests
# ------------------------------------------------------------------


class TestParsePDF:
    def _create_test_pdf(self, tmp_path: Path, pages: list[str]) -> Path:
        """Create a minimal PDF for testing."""
        import fitz

        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        for page_text in pages:
            page = doc.new_page()
            page.insert_text((72, 72), page_text)
        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    def test_parse_single_page(self, tmp_path):
        pdf_path = self._create_test_pdf(tmp_path, ["Hello from page 1"])
        result = parse_pdf(pdf_path)
        assert result.filename == "test.pdf"
        assert result.total_pages == 1
        assert len(result.chunks) == 1
        assert "Hello from page 1" in result.chunks[0].text
        assert result.chunks[0].page == 1

    def test_parse_multi_page(self, tmp_path):
        pdf_path = self._create_test_pdf(
            tmp_path,
            ["Page one content", "Page two content", "Page three content"],
        )
        result = parse_pdf(pdf_path)
        assert result.total_pages == 3
        assert len(result.chunks) == 3
        assert result.chunks[0].page == 1
        assert result.chunks[1].page == 2
        assert result.chunks[2].page == 3

    def test_parse_empty_page_skipped(self, tmp_path):
        import fitz

        pdf_path = tmp_path / "empty.pdf"
        doc = fitz.open()
        doc.new_page()  # Empty page
        page2 = doc.new_page()
        page2.insert_text((72, 72), "Content here")
        doc.save(str(pdf_path))
        doc.close()

        result = parse_pdf(pdf_path)
        assert result.total_pages == 2
        assert len(result.chunks) == 1
        assert result.chunks[0].page == 2

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_pdf("/nonexistent/file.pdf")

    def test_chunk_indices_across_pages(self, tmp_path):
        # Create pages with enough text to produce multiple chunks per page
        long_text = "\n\n".join([f"Sentence {i} " * 20 for i in range(10)])
        pdf_path = self._create_test_pdf(tmp_path, [long_text, long_text])
        result = parse_pdf(pdf_path)
        # Chunk indices should be globally sequential
        indices = [c.chunk_index for c in result.chunks]
        assert indices == list(range(len(result.chunks)))


# ------------------------------------------------------------------
# PPTX parsing tests
# ------------------------------------------------------------------


class TestParsePPTX:
    def _create_test_pptx(self, tmp_path: Path, slides: list[list[str]]) -> Path:
        """Create a minimal PPTX for testing."""
        from pptx import Presentation
        from pptx.util import Inches

        pptx_path = tmp_path / "test.pptx"
        prs = Presentation()
        for slide_texts in slides:
            slide = prs.slides.add_slide(prs.slide_layouts[5])  # Blank layout
            for i, text in enumerate(slide_texts):

                txBox = slide.shapes.add_textbox(Inches(1), Inches(1 + i), Inches(8), Inches(1))
                txBox.text_frame.text = text
            prs.save(str(pptx_path))
        return pptx_path

    def test_parse_single_slide(self, tmp_path):
        pptx_path = self._create_test_pptx(tmp_path, [["Hello from slide 1"]])
        result = parse_pptx(pptx_path)
        assert result.filename == "test.pptx"
        assert result.total_pages == 1
        assert len(result.chunks) == 1
        assert "Hello from slide 1" in result.chunks[0].text
        assert result.chunks[0].page == 1

    def test_parse_multi_slide(self, tmp_path):
        pptx_path = self._create_test_pptx(
            tmp_path,
            [["Slide 1"], ["Slide 2"], ["Slide 3"]],
        )
        result = parse_pptx(pptx_path)
        assert result.total_pages == 3
        assert len(result.chunks) == 3

    def test_multiple_shapes_on_slide(self, tmp_path):
        pptx_path = self._create_test_pptx(
            tmp_path,
            [["Title text", "Body text", "Footer text"]],
        )
        result = parse_pptx(pptx_path)
        assert len(result.chunks) == 1
        text = result.chunks[0].text
        assert "Title text" in text
        assert "Body text" in text
        assert "Footer text" in text

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_pptx("/nonexistent/file.pptx")


# ------------------------------------------------------------------
# parse_document auto-detection tests
# ------------------------------------------------------------------


class TestParseDocument:
    def test_pdf_auto_detect(self, tmp_path):
        import fitz

        pdf_path = tmp_path / "auto.pdf"
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((72, 72), "Auto detected PDF")
        doc.save(str(pdf_path))
        doc.close()

        result = parse_document(pdf_path)
        assert result.filename == "auto.pdf"
        assert "Auto detected PDF" in result.chunks[0].text

    def test_pptx_auto_detect(self, tmp_path):
        from pptx import Presentation
        from pptx.util import Inches

        pptx_path = tmp_path / "auto.pptx"
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
        txBox.text_frame.text = "Auto detected PPTX"
        prs.save(str(pptx_path))

        result = parse_document(pptx_path)
        assert result.filename == "auto.pptx"

    def test_unsupported_format(self, tmp_path):
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("hello")
        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_document(txt_path)
