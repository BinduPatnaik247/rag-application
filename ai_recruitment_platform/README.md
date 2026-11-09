# AI Enabled Recruitment Platform

A Python/FastAPI recruitment workspace for **private document ingestion, semantic retrieval, source-grounded questions and human-reviewed resume matching**. Supports PDF, Word `.docx`, and Excel `.xlsx` files. The API, browser UI, SQLAlchemy data model, migrations, audits, ACLs, tests, and Docker setup are included.

## Features

|Requirement|Implementation|
|-|-|
|PDF/DOCX/XLSX uploads and parsing|`app/services/parsing.py`; source units retain PDF page / Word paragraph and table / Excel sheet and row references|
|Text chunking|LangChain `RecursiveCharacterTextSplitter` in installed deployments; deterministic fallback in offline demo|
|Embeddings|LangChain `OpenAIEmbeddings` with OpenAI `text-embedding-3-small` in live mode|
|Vector database|Qdrant upsert, delete and filtered cosine search in live mode; local SQLite vector index for offline testing|
|Semantic search|Qdrant cosine retrieval; **lexical similarity only** in offline demo|
|RAG Q\&A|OpenAI Responses API with retrieved source excerpts and answer markers `\[1]` / `\[2]`; structured references include document, page/sheet and chunk ID|
|User-level security|Tenant-scoped JWT identity, admin/recruiter/candidate roles, private docs, owner/admin permissions, per-user grants/revocations, Qdrant ACL filtering|
|Redis|Optional tenant/user/ACL-scoped embedding and search cache, TTL-based; live stack supplies Redis|
|Recruitment|Jobs, candidate records, document attachments, resume-to-job evidence search, audit events, dashboard|

### Architecture

```
Browser / API consumer
       |
FastAPI + JWT + Argon2
       |
Tenant / document grants checked against PostgreSQL
       |
Uploaded file --> pypdf / python-docx / openpyxl parser
       |              --> LangChain recursive text chunks
       |              --> LangChain OpenAIEmbeddings --> Qdrant vectors
       |              --> SQLAlchemy chunk provenance + stored original
       |
Authorized search --> ACL-filtered Qdrant --> SQL provenance recheck
       |
Question --> OpenAI Responses API (grounded prompt) --> cited answer
       |
Redis cache: tenant + user + current ACL + content digest scoped
```

## Quick start — offline demo

**Python 3.11+**; in a terminal from the extracted project folder:

```bash
python -m venv .venv
source .venv/bin/activate 

pip install -r requirements.txt
cp .env.example .env
# Edit .env to set AI\_MODE=demo and a strong JWT\_SECRET.
python -m uvicorn app.main:app --reload
```

Open **http://localhost:8000** to use the included web dashboard, or **http://localhost:8000/docs** for interactive API docs. In demo mode, SQLite tables are automatically initialized and text vectors are stored in SQLite. 



Flow: 

1. Select **Account → Create a new organization** to create an independent tenant and first administrator. Log in with your email/password if already registered.
2. Open **Documents** to upload a PDF/DOCX/XLSX resume, job description or policy document. You can search only documents you own, have been granted, or administer.
3. Use **Search \& Ask** to retrieve ranked chunks and get an answer with structured document/page/sheet citations.
4. As an administrator, create recruiter and candidate users under **Access control**. Grant a recruiter explicit document access via document ID and user ID; verify they can search it and lose access after revocation.
5. Create a job under **Jobs \& Candidates**. Use **Match accessible resumes** for an evidence-ranked shortlist. Human recruiters must evaluate the underlying information themselves.

### Example API usage

Create a tenant and admin:

```bash
curl -X POST http://localhost:8000/api/v1/auth/bootstrap \\
  -H 'Content-Type: application/json' \\
  -d '{"company":"Acme Talent","name":"Admin One","email":"admin@example.com","password":"a-long-unique-password"}'
```

Copy `access\_token` from the response into your shell:

```bash
TOKEN='paste-token-here'
curl -X POST http://localhost:8000/api/v1/documents/upload \\
  -H "Authorization: Bearer $TOKEN" -F kind=resume -F file=@resume.pdf
curl -X POST http://localhost:8000/api/v1/search \\
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \\
  -d '{"query":"Python and machine learning experience","top\_k":5}'
curl -X POST http://localhost:8000/api/v1/ask \\
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \\
  -d '{"question":"Which documents mention scalable Python services?"}'
```

## Live AI mode — OpenAI + Qdrant + Redis

Set `.env` with a real key, secret and PostgreSQL password :

```ini
AI\_MODE=live
OPENAI\_API\_KEY=your-api-key
OPENAI\_EMBEDDING\_MODEL=text-embedding-3-small
OPENAI\_CHAT\_MODEL=gpt-4.1-mini
EMBEDDING\_DIMENSION=1536
JWT\_SECRET=replace-with-at-least-32-unpredictable-characters
POSTGRES\_PASSWORD=replace-with-a-strong-db-password
```

Then run:

```bash
docker compose up --build
```

The Compose stack launches FastAPI, PostgreSQL, Qdrant, and Redis. The API runs the Alembic migration on startup. **The three dependencies are implemented but have not been exercised against live services as part of this deliverable.** You must run an environment-specific integration smoke test and secure infrastructure before using real data.

> Changing embedding dimensions or models requires \*\*re-embedding\*\* all documents and choosing a new Qdrant collection. Do not point differently sized embeddings at an existing collection.

## API endpoints

|Method|Path|Permission|
|-|-|-|
|POST|`/api/v1/auth/bootstrap`|Creates new tenant and administrator|
|POST|`/api/v1/auth/login`|Public credentials exchange|
|GET|`/api/v1/auth/me`|Authenticated user|
|POST / GET|`/api/v1/users`|Administrator|
|POST / GET|`/api/v1/jobs`|POST: admin/recruiter; GET: authenticated|
|POST / GET|`/api/v1/candidates`|Admin/recruiter|
|POST|`/api/v1/documents/upload`|Authenticated; candidates upload only own unlinked resumes|
|GET|`/api/v1/documents`|Only accessible docs|
|GET|`/api/v1/documents/{id}`|Owner, admin, explicitly granted user|
|GET|`/api/v1/documents/{id}/download`|Owner, admin, explicitly granted user|
|POST|`/api/v1/documents/{id}/grants`|Owner/admin only|
|DELETE|`/api/v1/documents/{id}/grants/{user\_id}`|Owner/admin only|
|DELETE|`/api/v1/documents/{id}`|Owner/admin only|
|POST|`/api/v1/search`|Search only currently permitted documents|
|POST|`/api/v1/ask`|Source-grounded Q\&A over currently permitted docs|
|POST|`/api/v1/jobs/{id}/matches`|Admin/recruiter, permitted resumes only|
|GET|`/api/v1/audit`|Tenant administrator|

## Testing \& migrations

```bash
pip install -r requirements-dev.txt
pytest -q
python -m compileall -q app
alembic upgrade head
alembic check
```

The tests run in live mode, creating Word, Excel and PDF files in memory. They cover actual upload/search, permissions, cross-tenant isolation, grant/revoke, API authentication, file validation, candidate restrictions, job match authorization, PDF/DOCX/XLSX source references, deletion, migration consistency and CORS.

