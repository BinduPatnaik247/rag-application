"""Safely parse PDF, Word and Excel files into source-addressable segments."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from fastapi import HTTPException


@dataclass(frozen=True)
class Segment:
    text: str
    location: str  # PDF page, DOCX paragraph/table, or Excel sheet and row


ALLOWED = {".pdf", ".docx", ".xlsx"}
MAX_SEGMENTS = 10000
MAX_TEXT_CHARS = 1_000_000


def extract(filename: str, raw: bytes) -> list[Segment]:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(415, "Only searchable PDF, DOCX and XLSX files are supported")
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw), strict=False)
            if len(reader.pages) > 250:
                raise ValueError("PDF exceeds 250 pages")
            segments = [Segment(page.extract_text() or "", f"page {i}")
                        for i, page in enumerate(reader.pages, start=1)]
        elif suffix == ".docx":
            from docx import Document
            doc = Document(BytesIO(raw))
            segments = [Segment(p.text, f"paragraph {i}")
                        for i, p in enumerate(doc.paragraphs, start=1)]
            for table_index, table in enumerate(doc.tables, start=1):
                for row_index, row in enumerate(table.rows, start=1):
                    segments.append(Segment(" | ".join(c.text for c in row.cells),
                                            f"table {table_index} row {row_index}"))
        else:
            from openpyxl import load_workbook
            wb = load_workbook(BytesIO(raw), read_only=True, data_only=True, keep_links=False)
            segments = []
            try:
                for ws in wb.worksheets[:30]:
                    for row_number, row in enumerate(ws.iter_rows(values_only=True), start=1):
                        if row_number > 5000:
                            break
                        values = [str(c).strip()[:1000] for c in row if c is not None]
                        if values:
                            segments.append(Segment(" | ".join(values),
                                                    f"sheet {ws.title!r} row {row_number}"))
            finally:
                wb.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "Cannot read this file; it may be corrupt or unsupported") from exc
    usable = [Segment(re.sub(r"\s+", " ", s.text).strip(), s.location)
              for s in segments if s.text and s.text.strip()]
    if not usable:
        raise HTTPException(422, "No selectable text found (OCR is not enabled)")
    if len(usable) > MAX_SEGMENTS or sum(len(s.text) for s in usable) > MAX_TEXT_CHARS:
        raise HTTPException(413, "Document contains too much text")
    return usable


def chunk_segments(segments: list[Segment], chunk_size: int = 800, overlap: int = 120):
    """LangChain recursive splitter, with a deterministic offline fallback."""
    if not 0 <= overlap < chunk_size:
        raise ValueError("Invalid chunk sizing")
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size,
                                                  chunk_overlap=overlap,
                                                  separators=["\n\n", ". ", " ", ""])
        split = splitter.split_text
    except ImportError:
        def split(text):
            chunks = []
            step = chunk_size - overlap
            for i in range(0, len(text), step):
                chunks.append(text[i:i + chunk_size])
                if i + chunk_size >= len(text):
                    break
            return chunks
    return [(part, s.location) for s in segments for part in split(s.text) if part.strip()]
