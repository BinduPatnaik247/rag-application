from io import BytesIO
import pytest
from fastapi import HTTPException
from app.services.parsing import extract, chunk_segments, Segment


def test_docx_paragraphs_and_tables():
    from docx import Document
    doc = Document()
    doc.add_paragraph("Python and FastAPI developer experienced in recruitment automation")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Skills"
    table.cell(0, 1).text = "Qdrant, RAG"
    raw = BytesIO(); doc.save(raw)
    segments = extract("cv.docx", raw.getvalue())
    assert any("FastAPI" in s.text and "paragraph" in s.location for s in segments)
    assert any("Qdrant" in s.text and "table" in s.location for s in segments)


def test_xlsx_sheet_and_row_references():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active; ws.title = "Recruiting pipeline"
    ws.append(["Name", "Skill"])
    ws.append(["Candidate One", "Python"])
    out = BytesIO(); wb.save(out)
    segments = extract("candidates.xlsx", out.getvalue())
    assert any("Candidate One" in s.text and "row 2" in s.location for s in segments)
    assert any("Recruiting pipeline" in s.location for s in segments)


def test_pdf_page_citations():
    from reportlab.pdfgen import canvas
    out = BytesIO()
    pdf = canvas.Canvas(out)
    pdf.drawString(50, 700, "Candidate resume: Python, AWS and FastAPI")
    pdf.showPage(); pdf.drawString(50, 700, "Second page: Docker deployment")
    pdf.save()
    segments = extract("cv.pdf", out.getvalue())
    assert len(segments) == 2
    assert segments[0].location == "page 1"
    assert segments[1].location == "page 2"


def test_chunking_preserves_source_labels():
    parts = chunk_segments([Segment("Cloud infrastructure " * 120, "page 3")],
                           chunk_size=90, overlap=10)
    assert len(parts) > 10
    assert all(p[1] == "page 3" and len(p[0]) <= 90 for p in parts)


def test_bad_files_and_non_searchable_pdf():
    with pytest.raises(HTTPException) as e:
        extract("file.exe", b"hello")
    assert e.value.status_code == 415
    with pytest.raises(HTTPException) as e:
        extract("file.pdf", b"not pdf")
    assert e.value.status_code == 422


def test_empty_and_invalid_chunking():
    with pytest.raises(HTTPException):
        extract("resume.docx", b"bad")
    with pytest.raises(ValueError):
        chunk_segments([Segment("x", "page 1")], chunk_size=10, overlap=10)
