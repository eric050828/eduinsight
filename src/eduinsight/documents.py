"""Document parsing and chunking for RAG (Retrieval-Augmented Generation).

Extracts text from PDF and PPTX files, converts to Markdown, then splits
into chunks suitable for embedding and retrieval via Lite-Mem.

Supported formats:
- PDF (via pymupdf4llm)
- PPTX (via python-pptx, slide → ## heading)

Each chunk carries an `anchor_id` so the frontend can scroll the
markdown viewer to the cited section when a student clicks a citation.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """A chunk of text extracted from a document."""

    text: str
    source: str  # filename
    page: int | None = None  # page number (1-based) or slide number
    chunk_index: int = 0  # position within the document
    heading: str = ""  # nearest section heading
    anchor_id: str = ""  # slug for scroll-to-anchor in frontend


@dataclass
class ParsedMarkdown:
    """Markdown representation of a document, plus chunks for RAG."""

    filename: str
    markdown: str
    total_pages: int
    chunks: list[DocumentChunk] = field(default_factory=list)


def slugify(text: str) -> str:
    """Make a stable URL-safe anchor id from a heading.

    CJK is preserved (Next.js / browser supports unicode anchors).
    Returns the pure slug. Caller is responsible for de-duplicating
    repeated headings (e.g. by appending "-2", "-3").
    """
    text = unicodedata.normalize("NFKC", text or "").strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w一-鿿\-]+", "", text)
    text = text[:60].strip("-").lower()
    return text or "section"


def split_markdown_by_headings(
    markdown: str,
    *,
    source: str,
    max_chars: int = 1200,
) -> list[DocumentChunk]:
    """Split markdown by ## (and #) headings into chunks.

    Each chunk is one section (heading + body). If a section exceeds
    max_chars it is further split on paragraph boundaries while preserving
    the same heading/anchor.
    """
    chunks: list[DocumentChunk] = []
    # Split on H1/H2 lines; keep heading with its body
    parts = re.split(r"(?m)^(#{1,3} +.+)$", markdown)
    if parts and parts[0].strip():
        chunks.append(DocumentChunk(
            text=parts[0].strip(),
            source=source,
            heading="（前言）",
            anchor_id="preamble",
            chunk_index=0,
        ))
    chunk_idx = len(chunks)
    used_anchors: dict[str, int] = {}
    for i in range(1, len(parts), 2):
        heading_line = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        heading_text = re.sub(r"^#{1,3}\s+", "", heading_line)
        base_slug = slugify(heading_text)
        seen = used_anchors.get(base_slug, 0)
        used_anchors[base_slug] = seen + 1
        anchor = base_slug if seen == 0 else f"{base_slug}-{seen + 1}"
        section = (heading_line + "\n\n" + body).strip()
        if len(section) <= max_chars:
            chunks.append(DocumentChunk(
                text=section, source=source,
                heading=heading_text, anchor_id=anchor,
                chunk_index=chunk_idx,
            ))
            chunk_idx += 1
            continue
        # Section too long: split on paragraphs but reuse anchor
        paragraphs = re.split(r"\n\s*\n", section)
        buf = ""
        for p in paragraphs:
            if len(buf) + len(p) + 2 > max_chars and buf:
                chunks.append(DocumentChunk(
                    text=buf.strip(), source=source,
                    heading=heading_text, anchor_id=anchor,
                    chunk_index=chunk_idx,
                ))
                chunk_idx += 1
                buf = p
            else:
                buf = (buf + "\n\n" + p) if buf else p
        if buf.strip():
            chunks.append(DocumentChunk(
                text=buf.strip(), source=source,
                heading=heading_text, anchor_id=anchor,
                chunk_index=chunk_idx,
            ))
            chunk_idx += 1
    return chunks


@dataclass
class ParsedDocument:
    """Result of parsing a document file."""

    filename: str
    total_pages: int
    chunks: list[DocumentChunk] = field(default_factory=list)


def chunk_text(
    text: str,
    *,
    chunk_size: int = 500,
    overlap: int = 50,
    source: str = "",
    page: int | None = None,
    start_index: int = 0,
) -> list[DocumentChunk]:
    """Split text into overlapping chunks of roughly equal size.

    Splits on paragraph boundaries when possible, falling back to
    sentence boundaries, then word boundaries.

    Args:
        text: The text to split.
        chunk_size: Target chunk size in characters.
        overlap: Number of characters to overlap between chunks.
        source: Source filename for metadata.
        page: Page/slide number for metadata.
        start_index: Starting chunk index for numbering.

    Returns:
        List of DocumentChunk objects.
    """
    text = text.strip()
    if not text:
        return []

    # If text fits in one chunk, return as-is
    if len(text) <= chunk_size:
        return [DocumentChunk(text=text, source=source, page=page, chunk_index=start_index)]

    # Split into paragraphs first
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[DocumentChunk] = []
    current = ""
    idx = start_index

    for para in paragraphs:
        # If adding this paragraph would exceed chunk_size
        if current and len(current) + len(para) + 2 > chunk_size:
            chunks.append(
                DocumentChunk(text=current.strip(), source=source, page=page, chunk_index=idx)
            )
            idx += 1
            # Overlap: keep the tail of the current chunk
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:] + "\n\n" + para
            else:
                current = para
        else:
            current = current + "\n\n" + para if current else para

    # Don't forget the last chunk
    if current.strip():
        chunks.append(
            DocumentChunk(text=current.strip(), source=source, page=page, chunk_index=idx)
        )

    return chunks


def parse_pdf(file_path: str | Path) -> ParsedDocument:
    """Extract text from a PDF file and split into chunks.

    Uses PyMuPDF for fast, accurate text extraction.
    Each page's text is chunked separately with page number metadata.

    Args:
        file_path: Path to the PDF file.

    Returns:
        ParsedDocument with chunks tagged by page number.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file is not a valid PDF.
    """
    import fitz  # PyMuPDF

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        raise ValueError(f"Failed to open PDF: {e}") from e

    filename = path.name
    total_pages = len(doc)
    all_chunks: list[DocumentChunk] = []
    chunk_idx = 0

    for page_num in range(total_pages):
        page = doc[page_num]
        text = page.get_text("text")  # type: ignore[attr-defined]
        if not text or not text.strip():
            continue

        page_chunks = chunk_text(
            text,
            source=filename,
            page=page_num + 1,  # 1-based
            start_index=chunk_idx,
        )
        all_chunks.extend(page_chunks)
        chunk_idx += len(page_chunks)

    doc.close()

    logger.info("Parsed PDF %s: %d pages, %d chunks", filename, total_pages, len(all_chunks))
    return ParsedDocument(filename=filename, total_pages=total_pages, chunks=all_chunks)


def parse_pptx(file_path: str | Path) -> ParsedDocument:
    """Extract text from a PPTX file and split into chunks.

    Extracts text from all shapes on each slide. Each slide's text
    is chunked with slide number metadata.

    Args:
        file_path: Path to the PPTX file.

    Returns:
        ParsedDocument with chunks tagged by slide number.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file is not a valid PPTX.
    """
    from pptx import Presentation

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PPTX not found: {path}")

    try:
        prs = Presentation(str(path))
    except Exception as e:
        raise ValueError(f"Failed to open PPTX: {e}") from e

    filename = path.name
    all_chunks: list[DocumentChunk] = []
    chunk_idx = 0
    total_slides = len(prs.slides)

    for slide_num, slide in enumerate(prs.slides, 1):
        texts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    para_text = paragraph.text.strip()
                    if para_text:
                        texts.append(para_text)

        if not texts:
            continue

        slide_text = "\n\n".join(texts)
        slide_chunks = chunk_text(
            slide_text,
            source=filename,
            page=slide_num,
            start_index=chunk_idx,
        )
        all_chunks.extend(slide_chunks)
        chunk_idx += len(slide_chunks)

    logger.info("Parsed PPTX %s: %d slides, %d chunks", filename, total_slides, len(all_chunks))
    return ParsedDocument(filename=filename, total_pages=total_slides, chunks=all_chunks)


def parse_document(file_path: str | Path) -> ParsedDocument:
    """Auto-detect file type and parse accordingly.

    Supports: .pdf, .pptx

    Args:
        file_path: Path to the document.

    Returns:
        ParsedDocument with extracted chunks.

    Raises:
        ValueError: If the file type is not supported.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return parse_pdf(path)
    elif suffix == ".pptx":
        return parse_pptx(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Supported: .pdf, .pptx")


# ====================================================================
# Markdown conversion (newer pipeline — used by /materials upload)
# ====================================================================


def pdf_to_markdown(file_path: str | Path) -> str:
    """Convert PDF to clean Markdown using pymupdf4llm.

    Preserves headings, lists, tables; strips repeated headers/footers.
    """
    import pymupdf4llm  # type: ignore

    path = Path(file_path)
    md = pymupdf4llm.to_markdown(str(path))
    return md or ""


def pptx_to_markdown(file_path: str | Path) -> str:
    """Convert PPTX to Markdown by mapping slide titles to ## headings.

    Each slide:
        ## {slide title or "投影片 N"}

        - bullet 1
        - bullet 2

        body paragraph...
    """
    from pptx import Presentation

    path = Path(file_path)
    prs = Presentation(str(path))
    out: list[str] = []

    for idx, slide in enumerate(prs.slides, 1):
        title = ""
        # Find title placeholder
        for shape in slide.shapes:
            if shape.has_text_frame and shape.shape_type == 14:  # PLACEHOLDER
                title = shape.text_frame.text.strip()
                break
        if not title:
            # First non-empty text frame becomes title
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text_frame.text.strip():
                    lines = [
                        ln for ln in shape.text_frame.text.splitlines() if ln.strip()
                    ]
                    if lines:
                        title = lines[0].strip()
                    break
        if not title:
            title = f"投影片 {idx}"
        out.append(f"## {title}\n")

        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                text = paragraph.text.strip()
                if not text or text == title:
                    continue
                # Treat indented text as bullet
                level = paragraph.level if paragraph.level is not None else 0
                indent = "  " * max(0, level)
                out.append(f"{indent}- {text}")
        out.append("")  # blank line between slides

    return "\n".join(out)


def to_markdown(file_path: str | Path) -> ParsedMarkdown:
    """Convert any supported file to Markdown + chunks for RAG.

    Returns ParsedMarkdown with the full markdown body and pre-chunked
    sections (each with an anchor_id pointing at the section heading).

    If markdown conversion produces no chunks (e.g. very short PDF with
    no headings), we fall back to legacy page-by-page text extraction
    so RAG always has something to index.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    filename = path.name

    if suffix == ".pdf":
        md = pdf_to_markdown(path)
    elif suffix == ".pptx":
        md = pptx_to_markdown(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Supported: .pdf, .pptx")

    chunks = split_markdown_by_headings(md, source=filename)
    pages = sum(1 for line in md.splitlines() if line.startswith("# ") or line.startswith("## "))

    # Fallback: very short or heading-less docs may produce no chunks.
    # Use the legacy page-aware parser so analytics + quiz still work.
    if not chunks:
        try:
            legacy = parse_document(path)
            md_lines = []
            for c in legacy.chunks:
                anchor = f"p-{c.page or 0}-c-{c.chunk_index}"
                heading = f"p.{c.page}" if c.page else f"段落 {c.chunk_index + 1}"
                md_lines.append(f"## {heading}\n\n{c.text}")
                chunks.append(DocumentChunk(
                    text=c.text,
                    source=filename,
                    page=c.page,
                    chunk_index=c.chunk_index,
                    heading=heading,
                    anchor_id=anchor,
                ))
            md = "\n\n".join(md_lines)
            pages = legacy.total_pages
        except Exception:  # noqa: BLE001
            pass

    return ParsedMarkdown(
        filename=filename,
        markdown=md,
        total_pages=max(pages, 1),
        chunks=chunks,
    )
