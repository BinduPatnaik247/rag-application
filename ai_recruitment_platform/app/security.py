"""Passwords, JWT sessions and tenant-aware authorization helpers."""
from datetime import datetime, timedelta, timezone
from typing import Annotated
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import select, or_
from .config import settings
from .db import get_db
from .models import Document, DocumentGrant, User

_hasher = PasswordHasher()
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _hasher.verify(encoded, password)
    except (VerifyMismatchError, VerificationError):
        return False


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user.id, "tenant": user.tenant_id, "iat": now,
                       "exp": now + timedelta(minutes=settings.jwt_minutes)},
                      settings.jwt_secret, algorithm="HS256")


def current_user(token: Annotated[str, Depends(oauth2)],
                 db: Annotated[Session, Depends(get_db)]) -> User:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user = db.get(User, payload["sub"])
        if not user or not user.is_active or user.tenant_id != payload.get("tenant"):
            raise ValueError("Invalid session")
        return user
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired credentials") from exc


def require_roles(user: User, *roles: str):
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="Not permitted for your role")


def permitted_documents(db: Session, user: User) -> list[Document]:
    query = select(Document).where(Document.tenant_id == user.tenant_id,
                                   Document.status == "ready")
    if user.role != "admin":
        grant_subquery = select(DocumentGrant.document_id).where(
            DocumentGrant.tenant_id == user.tenant_id, DocumentGrant.user_id == user.id)
        query = query.where(or_(Document.owner_id == user.id,
                                Document.id.in_(grant_subquery)))
    return list(db.scalars(query.order_by(Document.id)).all())


def get_authorized_document(db: Session, user: User, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if not doc or doc.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Document not found")
    if user.role != "admin" and doc.owner_id != user.id:
        granted = db.scalar(select(DocumentGrant.id).where(
            DocumentGrant.tenant_id == user.tenant_id,
            DocumentGrant.document_id == document_id,
            DocumentGrant.user_id == user.id))
        if not granted:
            raise HTTPException(status_code=404, detail="Document not found")
    return doc


def may_manage_document(user: User, document: Document):
    if user.role != "admin" and document.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only owner or admin can change sharing")
