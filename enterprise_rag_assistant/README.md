# Enterprise AI Knowledge Assistant (Python RAG)

A runnable starter application featuring PDF/DOCX/TXT/XLSX ingestion, chunking, local embeddings, persistent Chroma storage, RAG answers with source citations, role-aware retrieval, a FastAPI backend, and Streamlit UI.

## Setup
Requires Python 3.10+.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Windows: copy .env.example .env
# macOS/Linux: cp .env.example .env
```

Optionally add `OPENAI_API_KEY` to `.env`. Without it, the app provides a grounded extractive fallback.

## Run
Terminal 1:
```bash
uvicorn app.main:app --reload
```
Terminal 2:
```bash
streamlit run app/ui.py
```
Open the Streamlit URL shown in the terminal. API docs: http://127.0.0.1:8000/docs

## Use
1. Enter a demo user ID and roles (`employee`, `hr`, or `admin`).
2. Upload a PDF, DOCX, TXT, or XLSX file.
3. Set allowed roles for that document, e.g. `employee,hr`.
4. Ask a question. The answer includes source filename and chunk citations.

## API
- `GET /health`
- `POST /documents/upload` multipart: `file`, `uploaded_by`, `allowed_roles`
- `POST /chat` JSON: `question`, `user_id`, `roles`, `top_k`
- `GET /documents`

## Architecture
Streamlit UI -> FastAPI -> parser -> chunker -> Sentence Transformers embeddings -> Chroma.
Questions -> role-filtered retrieval -> prompt/context -> OpenAI (optional) -> cited answer.

## Production hardening required
This is a learning/MVP starter, not production-certified. The demo accepts roles from the client. Replace this with verified OIDC/JWT authentication and trusted server-side role claims. Also add tenant isolation, audit logs, encryption, malware scanning, rate limits, file retention controls, secrets management, monitoring, and evaluation tests. Treat retrieved documents as untrusted input. Do not send confidential data to external models unless approved by your organization.
