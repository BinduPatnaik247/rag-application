from io import BytesIO
from docx import Document as WordDocument
from tests.conftest import make_user


def resume_bytes(text="Python FastAPI engineer with Docker Kubernetes vector search Qdrant RAG experience"):
    doc = WordDocument()
    doc.add_paragraph(text)
    buf = BytesIO(); doc.save(buf)
    return buf.getvalue()


def upload(client, headers, text="Python FastAPI engineer with Docker Kubernetes vector search", kind="resume"):
    return client.post("/api/v1/documents/upload", headers=headers,
       data={"kind": kind},
       files={"file": ("resume.docx", resume_bytes(text),
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})


def test_end_to_end_document_search_and_source_citations(client, admin):
    uploaded = upload(client, admin["header"])
    assert uploaded.status_code == 201, uploaded.text
    doc = uploaded.json()
    assert doc["status"] == "ready" and doc["chunk_count"] >= 1
    search = client.post("/api/v1/search", headers=admin["header"], json={
        "query": "FastAPI Docker", "top_k": 5})
    assert search.status_code == 200, search.text
    assert search.json()["results"][0]["document_id"] == doc["id"]
    assert search.json()["search_type"] == "lexical-demo"
    answer = client.post("/api/v1/ask", headers=admin["header"], json={
        "question": "Which resume mentions FastAPI and Docker?"})
    assert answer.status_code == 200, answer.text
    result = answer.json()
    assert "[1]" in result["answer"]
    assert result["citations"][0]["document_id"] == doc["id"]
    assert result["model"] == "extractive-demo"
    assert result["human_review_required"] is True
    download = client.get(f"/api/v1/documents/{doc['id']}/download", headers=admin["header"])
    assert download.status_code == 200
    assert download.content[:2] == b"PK"


def test_permission_grant_revoke_and_search(client, admin):
    recruiter = make_user(client, admin, "Recruiter One", "recruiter@northwind.example", "recruiter")
    doc_id = upload(client, admin["header"]).json()["id"]
    assert client.get("/api/v1/documents", headers=recruiter["header"]).json() == []
    assert client.post("/api/v1/search", headers=recruiter["header"],
                       json={"query": "FastAPI"}).json()["results"] == []
    assert client.get(f"/api/v1/documents/{doc_id}/download", headers=recruiter["header"]).status_code == 404
    shared = client.post(f"/api/v1/documents/{doc_id}/grants", headers=admin["header"],
                         json={"user_id": recruiter["id"]})
    assert shared.status_code == 201, shared.text
    assert len(client.get("/api/v1/documents", headers=recruiter["header"]).json()) == 1
    assert len(client.post("/api/v1/search", headers=recruiter["header"],
                           json={"query": "FastAPI"}).json()["results"]) >= 1
    revoke = client.delete(f"/api/v1/documents/{doc_id}/grants/{recruiter['id']}",
                           headers=admin["header"])
    assert revoke.status_code == 200
    assert client.post("/api/v1/search", headers=recruiter["header"],
                       json={"query": "FastAPI"}).json()["results"] == []
    assert client.post("/api/v1/ask", headers=recruiter["header"],
                       json={"question": "What is in the resume?"}).json()["citations"] == []
    assert client.get(f"/api/v1/documents/{doc_id}/download", headers=recruiter["header"]).status_code == 404
    assert client.post("/api/v1/search", headers=recruiter["header"],
                       json={"query": "FastAPI", "document_ids": [doc_id]}).status_code == 404


def test_tenant_isolation_on_documents_and_grants(client, admin):
    other_tenant = client.post("/api/v1/auth/bootstrap", json={
        "company": "Other Employer", "name": "Other Admin",
        "email": "admin@other.example", "password": "another secure password"}).json()
    other = {"Authorization": "Bearer " + other_tenant["access_token"]}
    document_id = upload(client, admin["header"]).json()["id"]
    assert client.get(f"/api/v1/documents/{document_id}", headers=other).status_code == 404
    assert client.get(f"/api/v1/documents/{document_id}/download", headers=other).status_code == 404
    assert client.post(f"/api/v1/documents/{document_id}/grants", headers=other,
                       json={"user_id": admin["user_id"]}).status_code == 404
    assert client.post(f"/api/v1/documents/{document_id}/grants", headers=admin["header"],
                       json={"user_id": other_tenant["user_id"]}).status_code == 404
    assert client.post("/api/v1/search", headers=other,
                       json={"query": "FastAPI"}).json()["results"] == []


def test_candidate_role_upload_restrictions(client, admin):
    candidate = make_user(client, admin, "Applicant One", "candidate@northwind.example", "candidate")
    assert upload(client, candidate["header"], kind="policy").status_code == 403
    assert upload(client, candidate["header"]).status_code == 201
    assert client.post("/api/v1/jobs", headers=candidate["header"], json={
        "title": "Senior Developer", "description": "Expert Python full-stack developer position"}).status_code == 403
    assert client.get("/api/v1/users", headers=candidate["header"]).status_code == 403
    assert client.get("/api/v1/candidates", headers=candidate["header"]).status_code == 403


def test_job_creation_and_evidence_matches(client, admin):
    job = client.post("/api/v1/jobs", headers=admin["header"], json={
        "title": "AI Backend Engineer",
        "description": "Python FastAPI Docker vector search experience required for recruiting platform"})
    assert job.status_code == 201
    upload(client, admin["header"], text="Python FastAPI Docker veteran building web APIs")
    matches = client.post(f"/api/v1/jobs/{job.json()['id']}/matches", headers=admin["header"])
    assert matches.status_code == 200, matches.text
    assert matches.json()["matches"]
    assert "human review" in matches.json()["decision_policy"].lower()
    assert client.post("/api/v1/jobs/nonexistent/matches", headers=admin["header"]).status_code == 404


def test_owner_can_manage_grants_and_non_owner_cannot(client, admin):
    a = make_user(client, admin, "Recruiter A", "a@northwind.example", "recruiter")
    b = make_user(client, admin, "Recruiter B", "b@northwind.example", "recruiter")
    c = make_user(client, admin, "Recruiter C", "c@northwind.example", "recruiter")
    doc_id = upload(client, a["header"]).json()["id"]
    assert client.post(f"/api/v1/documents/{doc_id}/grants", headers=b["header"],
                       json={"user_id": c["id"]}).status_code == 404
    assert client.post(f"/api/v1/documents/{doc_id}/grants", headers=a["header"],
                       json={"user_id": c["id"]}).status_code == 201
    assert client.post(f"/api/v1/documents/{doc_id}/grants", headers=c["header"],
                       json={"user_id": b["id"]}).status_code == 403


def test_file_validation_audit_and_deletion(client, admin):
    bad = client.post("/api/v1/documents/upload", headers=admin["header"],
                      data={"kind": "resume"}, files={"file": ("malware.exe", b"garbage")})
    assert bad.status_code == 415
    bad2 = client.post("/api/v1/documents/upload", headers=admin["header"],
                       data={"kind": "resume"}, files={"file": ("fake.pdf", b"garbage")})
    assert bad2.status_code == 422
    doc_id = upload(client, admin["header"]).json()["id"]
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=admin["header"]).status_code == 200
    assert client.get(f"/api/v1/documents/{doc_id}", headers=admin["header"]).status_code == 404
    assert client.post("/api/v1/search", headers=admin["header"],
                       json={"query": "Docker"}).json()["results"] == []
    history = client.get("/api/v1/audit", headers=admin["header"])
    assert history.status_code == 200
    assert "document_deleted" in [event["event"] for event in history.json()]


def test_auth_and_validation(client, admin):
    assert client.get("/api/v1/documents").status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "email": "admin@northwind.example", "password": "wrong"}).status_code == 401
    assert client.post("/api/v1/auth/bootstrap", json={
        "company": "X", "name": "X", "email": "invalid", "password": "short"}).status_code == 422
    assert client.post("/api/v1/ask", headers=admin["header"],
                       json={"question": "x"}).status_code == 422
    assert client.post("/api/v1/search", headers=admin["header"],
                       json={"query": "Docker", "top_k": 999}).status_code == 422


def test_cors_preflight(client):
    response = client.options("/api/v1/documents/document-id/grants/user-id", headers={
        "Origin": "http://localhost:8000", "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "authorization"})
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:8000"


def test_pdf_and_xlsx_upload_search_citations(client, admin):
    from reportlab.pdfgen import canvas
    from openpyxl import Workbook
    pdf_bytes = BytesIO()
    c = canvas.Canvas(pdf_bytes)
    c.drawString(70, 700, "Recruitment process manual: structured technical interviews")
    c.showPage()
    c.save()
    pdf = client.post("/api/v1/documents/upload", headers=admin["header"],
        data={"kind": "policy"},
        files={"file": ("manual.pdf", pdf_bytes.getvalue(), "application/pdf")})
    assert pdf.status_code == 201, pdf.text
    wb = Workbook()
    ws = wb.active
    ws.title = "Skills Matrix"
    ws.append(["Candidate", "Experience"])
    ws.append(["Synthetic Candidate", "Python data engineering and Qdrant vector search"])
    workbook = BytesIO(); wb.save(workbook)
    xlsx = client.post("/api/v1/documents/upload", headers=admin["header"],
        data={"kind": "other"}, files={"file": ("matrix.xlsx", workbook.getvalue(),
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert xlsx.status_code == 201, xlsx.text
    pdf_hits = client.post("/api/v1/search", headers=admin["header"], json={
        "query": "technical interviews", "kind": "policy"}).json()["results"]
    excel_hits = client.post("/api/v1/search", headers=admin["header"], json={
        "query": "Python Qdrant", "kind": "other"}).json()["results"]
    assert any("page 1" in hit["location"] for hit in pdf_hits)
    assert any("Skills Matrix" in hit["location"] for hit in excel_hits)


def test_recruiters_cannot_match_unshared_candidate_resumes(client, admin):
    recruiter = make_user(client, admin, "Recruiter D", "d@northwind.example", "recruiter")
    job = client.post("/api/v1/jobs", headers=recruiter["header"], json={
        "title": "Backend Developer", "description": "Python FastAPI Docker services and cloud deployment"}).json()
    private_resume = upload(client, admin["header"]).json()
    matches = client.post(f"/api/v1/jobs/{job['id']}/matches", headers=recruiter["header"])
    assert matches.status_code == 200
    assert matches.json()["matches"] == []
    client.post(f"/api/v1/documents/{private_resume['id']}/grants", headers=admin["header"],
                json={"user_id": recruiter["id"]})
    matches = client.post(f"/api/v1/jobs/{job['id']}/matches", headers=recruiter["header"])
    assert matches.json()["matches"]
