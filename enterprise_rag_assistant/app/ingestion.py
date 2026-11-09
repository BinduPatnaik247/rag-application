from pathlib import Path
from pypdf import PdfReader
from docx import Document
from openpyxl import load_workbook
import re

SUPPORTED = {".pdf", ".docx", ".txt", ".xlsx"}

def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "\\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if suffix == ".docx":
        return "\\n".join(p.text for p in Document(path).paragraphs)
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".xlsx":
        workbook = load_workbook(path, read_only=True, data_only=True)
        rows = []
        for sheet in workbook.worksheets:
            rows.append(f"Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                values = [str(v) for v in row if v is not None]
                if values:
                    rows.append(" | ".join(values))
        return "\\n".join(rows)
    raise ValueError(f"Unsupported file type: {suffix}")

def chunk_text(text: str, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    clean = re.sub(r"\\s+", " ", text).strip()
    if not clean:
        return []
    chunks, start = [], 0
    while start < len(clean):
        end = min(start + chunk_size, len(clean))
        if end < len(clean):
            boundary = max(clean.rfind(". ", start, end), clean.rfind(" ", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        piece = clean[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(clean):
            break
        start = max(end - overlap, start + 1)
    return chunks
