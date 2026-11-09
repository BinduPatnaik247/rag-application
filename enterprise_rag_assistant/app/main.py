from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from app.config import MAX_FILE_MB
from app.ingestion import extract_text, chunk_text, SUPPORTED
from app.vector_store import add_chunks, list_documents
from app.schemas import ChatRequest, ChatResponse
from app.rag import answer_question

app = FastAPI(title="Enterprise AI Knowledge Assistant", version="1.0.0")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    uploaded_by: str = Form(...),
    allowed_roles: str = Form("employee")
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type: {suffix}")
    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_FILE_MB} MB limit.")
    if not content:
        raise HTTPException(400, "Uploaded file is empty.")
    temp_dir = Path("./data/uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    doc_id = str(uuid4())
    temp_path = temp_dir / f"{doc_id}{suffix}"
    temp_path.write_bytes(content)
    try:
        extracted = extract_text(temp_path)
        chunks = chunk_text(extracted)
        roles = [r.strip().lower() for r in allowed_roles.split(",") if r.strip()]
        if not roles:
            raise HTTPException(400, "At least one allowed role is required.")
        count = add_chunks(chunks, doc_id, Path(file.filename).name, uploaded_by, roles)
        return {"message": "Document indexed", "doc_id": doc_id,
                "filename": Path(file.filename).name, "chunks_indexed": count,
                "allowed_roles": roles}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Document processing failed: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    try:
        return answer_question(request.question, [r.lower() for r in request.roles], request.top_k)
    except Exception as exc:
        raise HTTPException(500, f"Question processing failed: {exc}") from exc

@app.get("/documents")
def documents():
    return {"documents": list_documents()}
