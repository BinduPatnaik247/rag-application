"""Recruitment workflows with explicit per-document ACL enforcement."""
import hashlib
import os
import re
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import (Tenant, User, Job, Candidate, Document, DocumentGrant,
                     Chunk, AuditEvent)
from .security import (current_user, create_token, hash_password, verify_password,
                       require_roles, permitted_documents, get_authorized_document,
                       may_manage_document)
from .services.parsing import extract, chunk_segments
from .services.embeddings import Embedder
from .services.vectors import VectorIndex
from .services.cache import Cache
from .services.helpers import stable_digest
from .services.rag import generate_answer

router = APIRouter(prefix="/api/v1")
Db = Annotated[Session, Depends(get_db)]
Me = Annotated[User, Depends(current_user)]


class BootstrapIn(BaseModel):
    company: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=128)


class LoginIn(BaseModel):
    email: str
    password: str


class NewUser(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    role: Literal["admin", "recruiter", "candidate"]


class JobIn(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=20, max_length=25000)


class CandidateIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=5, max_length=254)


class GrantIn(BaseModel):
    user_id: str


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=10)
    kind: Literal["resume", "job_description", "policy", "other"] | None = None
    document_ids: list[str] | None = Field(default=None, max_length=100)


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=10)
    kind: Literal["resume", "job_description", "policy", "other"] | None = None


def audit(db: Session, user: User, action: str, object_id: str, details: str = ""):
    db.add(AuditEvent(tenant_id=user.tenant_id, actor_id=user.id, event=action,
                      object_id=object_id, details=details[:500]))


def summary(document: Document):
    return {"id": document.id, "filename": document.filename, "kind": document.kind,
            "owner_id": document.owner_id, "candidate_id": document.candidate_id,
            "job_id": document.job_id, "status": document.status,
            "chunk_count": document.chunk_count, "created_at": document.created_at}


@router.get("/health")
def health():
    return {"status": "ok", "ai_mode": settings.ai_mode,
            "live_semantic_embeddings": settings.ai_mode == "live"}


@router.post("/auth/bootstrap", status_code=201)
def bootstrap(payload: BootstrapIn, db: Db):
    """Creates an entirely new tenant and its first admin; does not join existing tenants."""
    email = payload.email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    tenant = Tenant(name=payload.company.strip())
    db.add(tenant)
    db.flush()
    user = User(tenant_id=tenant.id, email=email, name=payload.name.strip(),
                password_hash=hash_password(payload.password), role="admin")
    db.add(user)
    db.flush()
    audit(db, user, "tenant_bootstrapped", tenant.id)
    db.commit()
    return {"tenant_id": tenant.id, "user_id": user.id, "access_token": create_token(user),
            "token_type": "bearer"}


@router.post("/auth/login")
def login(payload: LoginIn, db: Db):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": create_token(user), "token_type": "bearer",
            "role": user.role, "user_id": user.id, "tenant_id": user.tenant_id}


@router.get("/auth/me")
def me(user: Me):
    return {"id": user.id, "name": user.name, "role": user.role,
            "email": user.email, "tenant_id": user.tenant_id}


@router.post("/users", status_code=201)
def add_user(payload: NewUser, user: Me, db: Db):
    require_roles(user, "admin")
    email = payload.email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    new = User(tenant_id=user.tenant_id, email=email, name=payload.name,
               password_hash=hash_password(payload.password), role=payload.role)
    db.add(new)
    db.flush()
    audit(db, user, "user_created", new.id, payload.role)
    db.commit()
    return {"id": new.id, "role": new.role, "email": new.email}


@router.get("/users")
def users(user: Me, db: Db):
    require_roles(user, "admin")
    result = db.scalars(select(User).where(User.tenant_id == user.tenant_id)).all()
    return [{"id": u.id, "name": u.name, "role": u.role, "email": u.email} for u in result]


@router.post("/jobs", status_code=201)
def create_job(payload: JobIn, user: Me, db: Db):
    require_roles(user, "admin", "recruiter")
    job = Job(tenant_id=user.tenant_id, owner_id=user.id,
              title=payload.title, description=payload.description)
    db.add(job)
    db.flush()
    audit(db, user, "job_created", job.id)
    db.commit()
    return {"id": job.id, "title": job.title, "status": job.status}


@router.get("/jobs")
def list_jobs(user: Me, db: Db):
    result = db.scalars(select(Job).where(Job.tenant_id == user.tenant_id)).all()
    return [{"id": j.id, "title": j.title, "description": j.description, "status": j.status}
            for j in result]


@router.post("/candidates", status_code=201)
def create_candidate(payload: CandidateIn, user: Me, db: Db):
    require_roles(user, "admin", "recruiter")
    candidate = Candidate(tenant_id=user.tenant_id,
                          name=payload.name, email=payload.email.lower())
    db.add(candidate)
    db.flush()
    audit(db, user, "candidate_created", candidate.id)
    db.commit()
    return {"id": candidate.id, "name": candidate.name}


@router.get("/candidates")
def list_candidates(user: Me, db: Db):
    require_roles(user, "admin", "recruiter")
    result = db.scalars(select(Candidate).where(Candidate.tenant_id == user.tenant_id)).all()
    return [{"id": c.id, "name": c.name, "email": c.email} for c in result]


@router.post("/documents/upload", status_code=201)
async def upload_document(user: Me, db: Db, file: UploadFile = File(...),
                          kind: Literal["resume", "job_description", "policy", "other"] = Form(...),
                          candidate_id: str | None = Form(default=None),
                          job_id: str | None = Form(default=None)):
    if user.role == "candidate" and (kind != "resume" or candidate_id or job_id):
        raise HTTPException(403, "Candidates may only upload their own unlinked resumes")
    original = Path(file.filename or "").name
    if not original or len(original) > 255 or re.search(r"[\x00-\x1f\x7f]", original):
        raise HTTPException(422, "Invalid filename")
    raw = await file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(413, "File too large")
    if not raw:
        raise HTTPException(422, "Empty document")
    if candidate_id:
        candidate = db.get(Candidate, candidate_id)
        if not candidate or candidate.tenant_id != user.tenant_id:
            raise HTTPException(404, "Candidate not found")
    if job_id:
        job = db.get(Job, job_id)
        if not job or job.tenant_id != user.tenant_id:
            raise HTTPException(404, "Job not found")
    extracted = extract(original, raw)
    parts = chunk_segments(extracted)
    if not parts or len(parts) > 5000:
        raise HTTPException(422, "Could not produce a valid index")
    document_id = str(uuid4())
    savedir = Path(settings.upload_dir) / user.tenant_id
    savedir.mkdir(parents=True, exist_ok=True)
    dest = savedir / (document_id + Path(original).suffix.lower())
    # Avoid storing original untrusted filename as a path.
    dest.write_bytes(raw)
    doc = Document(id=document_id, tenant_id=user.tenant_id, owner_id=user.id,
                   filename=original, file_path=str(dest.resolve()), kind=kind,
                   candidate_id=candidate_id, job_id=job_id,
                   sha256=hashlib.sha256(raw).hexdigest(), status="indexing")
    db.add(doc)
    try:
        db.flush()
        embedder = Embedder()
        vectors = embedder.embed_many([text for text, _ in parts], user.tenant_id)
        if len(vectors) != len(parts):
            raise RuntimeError("Embedding count mismatch")
        rows = []
        for i, ((text, location), vector) in enumerate(zip(parts, vectors)):
            chunk = Chunk(tenant_id=user.tenant_id, document_id=doc.id,
                          ordinal=i, text=text, location=location)
            db.add(chunk)
            db.flush()
            rows.append((chunk.id, vector))
        VectorIndex(embedder.dimension).upsert(db, user.tenant_id, doc.id, rows)
        doc.chunk_count = len(rows)
        doc.status = "ready"
        audit(db, user, "document_indexed", doc.id, f"{kind}; {len(rows)} chunks")
        db.commit()
    except Exception:
        db.rollback()
        dest.unlink(missing_ok=True)
        # Qdrant write is not transactional with SQL: compensate if it succeeded.
        try:
            embedder = Embedder()
            VectorIndex(embedder.dimension).delete_document(db, user.tenant_id, doc.id)
        except Exception:
            pass
        raise HTTPException(503, "Document indexing failed; upload was not saved")
    return summary(doc)


@router.get("/documents")
def list_documents(user: Me, db: Db):
    return [summary(doc) for doc in permitted_documents(db, user)]


@router.get("/documents/{document_id}")
def detail(document_id: str, user: Me, db: Db):
    return summary(get_authorized_document(db, user, document_id))


@router.get("/documents/{document_id}/download")
def download(document_id: str, user: Me, db: Db):
    doc = get_authorized_document(db, user, document_id)
    path = Path(doc.file_path).resolve()
    root = Path(settings.upload_dir).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "File missing")
    return FileResponse(path, filename=doc.filename, media_type="application/octet-stream")


@router.post("/documents/{document_id}/grants", status_code=201)
def grant_document(document_id: str, payload: GrantIn, user: Me, db: Db):
    doc = get_authorized_document(db, user, document_id)
    may_manage_document(user, doc)
    target = db.get(User, payload.user_id)
    if not target or target.tenant_id != user.tenant_id or not target.is_active:
        raise HTTPException(404, "User not found")
    if target.id == doc.owner_id:
        raise HTTPException(409, "Document owner already has access")
    already = db.scalar(select(DocumentGrant.id).where(
        DocumentGrant.document_id == document_id, DocumentGrant.user_id == target.id,
        DocumentGrant.tenant_id == user.tenant_id))
    if already:
        raise HTTPException(409, "Permission already exists")
    new = DocumentGrant(tenant_id=user.tenant_id, document_id=doc.id,
                        user_id=target.id, granted_by=user.id)
    db.add(new)
    audit(db, user, "document_access_granted", doc.id, target.id)
    db.commit()
    return {"document_id": doc.id, "user_id": target.id, "access": "read"}


@router.delete("/documents/{document_id}/grants/{target_user_id}")
def revoke_document(document_id: str, target_user_id: str, user: Me, db: Db):
    doc = get_authorized_document(db, user, document_id)
    may_manage_document(user, doc)
    match = db.scalar(select(DocumentGrant).where(
        DocumentGrant.document_id == doc.id, DocumentGrant.user_id == target_user_id,
        DocumentGrant.tenant_id == user.tenant_id))
    if not match:
        raise HTTPException(404, "Grant not found")
    db.delete(match)
    audit(db, user, "document_access_revoked", doc.id, target_user_id)
    db.commit()
    return {"revoked": True}


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, user: Me, db: Db):
    doc = get_authorized_document(db, user, document_id)
    may_manage_document(user, doc)
    original_path = Path(doc.file_path)
    embedder = Embedder()
    try:
        VectorIndex(embedder.dimension).delete_document(db, user.tenant_id, doc.id)
    except Exception as exc:
        raise HTTPException(503, "Vector deletion failed; retry before deleting record") from exc
    db.execute(delete(DocumentGrant).where(DocumentGrant.tenant_id == user.tenant_id,
                                           DocumentGrant.document_id == doc.id))
    db.delete(doc)
    audit(db, user, "document_deleted", document_id)
    db.commit()
    original_path.unlink(missing_ok=True)
    return {"deleted": True}


def _search(db: Session, user: User, query: str, top_k: int,
            kind: str | None = None, document_ids: list[str] | None = None):
    allowed = permitted_documents(db, user)
    allowed_by_id = {doc.id: doc for doc in allowed}
    if document_ids is not None and any(doc_id not in allowed_by_id for doc_id in document_ids):
        raise HTTPException(404, "One or more documents not found")
    allowed = [doc for doc in allowed if (not kind or doc.kind == kind)
               and (document_ids is None or doc.id in document_ids)]
    if not allowed:
        return []
    ids = [doc.id for doc in allowed]
    # ACL key includes user, permitted document IDs AND content digests; revoked docs
    # change the ACL fingerprint, so old Redis answers never serve to a revoked user.
    acl = stable_digest([(doc.id, doc.sha256) for doc in allowed])
    cache = Cache()
    cached = cache.get("search", user.tenant_id, user.id, acl, query, top_k, kind, settings.ai_mode)
    if cached is not None:
        # Revalidate every returned chunk against the CURRENT allowed set.
        if all(hit["document_id"] in ids for hit in cached):
            return cached
    embedder = Embedder()
    hits = VectorIndex(embedder.dimension).search(db, user.tenant_id, ids,
                                                  embedder.embed(query, user.tenant_id), top_k)
    if not hits:
        return []
    chunks = {chunk.id: chunk for chunk in db.scalars(select(Chunk).where(
        Chunk.tenant_id == user.tenant_id, Chunk.document_id.in_(ids),
        Chunk.id.in_([hit[0] for hit in hits]))).all()}
    found = []
    for chunk_id, score in hits:
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        doc = allowed_by_id[chunk.document_id]
        found.append({"chunk_id": chunk.id, "document_id": doc.id,
                      "filename": doc.filename, "kind": doc.kind,
                      "location": chunk.location, "score": round(score, 5),
                      "text": chunk.text})
    cache.set("search", found, user.tenant_id, user.id, acl, query, top_k, kind,
              settings.ai_mode, ttl=60)
    return found


@router.post("/search")
def semantic_search(payload: SearchIn, user: Me, db: Db):
    matches = _search(db, user, payload.query, payload.top_k,
                      payload.kind, payload.document_ids)
    return {"mode": settings.ai_mode,
            "search_type": "semantic" if settings.ai_mode == "live" else "lexical-demo",
            "results": matches}


@router.post("/ask")
def ask(payload: AskIn, user: Me, db: Db):
    matches = _search(db, user, payload.question, payload.top_k, payload.kind)
    answer, model = generate_answer(payload.question, matches)
    references = [{"marker": f"[{i}]", "document_id": match["document_id"],
                   "chunk_id": match["chunk_id"], "filename": match["filename"],
                   "location": match["location"], "excerpt": match["text"][:500]}
                  for i, match in enumerate(matches, 1)]
    return {"answer": answer, "model": model, "citations": references,
            "human_review_required": True}


@router.post("/jobs/{job_id}/matches")
def match_resumes(job_id: str, user: Me, db: Db, top_k: int = 10):
    require_roles(user, "admin", "recruiter")
    job = db.get(Job, job_id)
    if not job or job.tenant_id != user.tenant_id:
        raise HTTPException(404, "Job not found")
    matches = _search(db, user, job.description[:1000], max(1, min(top_k, 10)), "resume")
    best = {}
    for hit in matches:
        if hit["document_id"] not in best or hit["score"] > best[hit["document_id"]]["score"]:
            best[hit["document_id"]] = hit
    return {"job_id": job.id, "job_title": job.title,
            "matches": sorted(best.values(), key=lambda x: -x["score"]),
            "decision_policy": "Evidence for human review only; never auto-hire or reject candidates",
            "mode": settings.ai_mode}


@router.get("/audit")
def audit_events(user: Me, db: Db):
    require_roles(user, "admin")
    events = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == user.tenant_id)
                       .order_by(AuditEvent.created_at.desc()).limit(100)).all()
    return [{"id": event.id, "event": event.event, "actor_id": event.actor_id,
             "object_id": event.object_id, "details": event.details,
             "created_at": event.created_at} for event in events]
