"""Real Qdrant vector database in live mode; local SQL similarity only in demo."""
import json
import math
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from ..config import settings
from ..models import DemoVector


class VectorIndex:
    def __init__(self, dimensions: int):
        self.dimensions = dimensions
        self.client = None
        if settings.ai_mode == "live":
            try:
                from qdrant_client import QdrantClient, models
            except ImportError as exc:
                raise RuntimeError("Install qdrant-client for live vector search") from exc
            self.models = models
            self.client = QdrantClient(url=settings.qdrant_url, timeout=15)
            if not self.client.collection_exists(settings.qdrant_collection):
                self.client.create_collection(settings.qdrant_collection,
                    vectors_config=models.VectorParams(size=dimensions,
                                                       distance=models.Distance.COSINE))
            existing_dim = self.client.get_collection(settings.qdrant_collection).config.params.vectors.size
            if existing_dim != dimensions:
                raise RuntimeError("Qdrant vector dimension mismatch: use a new collection")

    def upsert(self, db: Session, tenant_id: str, document_id: str, rows: list[tuple[str, list[float]]]):
        if self.client is not None:
            points = [self.models.PointStruct(
                id=chunk_id, vector=vec,
                payload={"tenant_id": tenant_id, "document_id": document_id,
                         "chunk_id": chunk_id}) for chunk_id, vec in rows]
            self.client.upsert(collection_name=settings.qdrant_collection,
                               points=points, wait=True)
        else:
            for chunk_id, vec in rows:
                db.add(DemoVector(chunk_id=chunk_id, tenant_id=tenant_id,
                                  document_id=document_id, vector_json=json.dumps(vec)))
            db.flush()

    def delete_document(self, db: Session, tenant_id: str, document_id: str):
        if self.client is not None:
            self.client.delete(collection_name=settings.qdrant_collection,
                points_selector=self.models.FilterSelector(filter=self.models.Filter(must=[
                    self.models.FieldCondition(key="tenant_id", match=self.models.MatchValue(value=tenant_id)),
                    self.models.FieldCondition(key="document_id", match=self.models.MatchValue(value=document_id))
                ])), wait=True)
        else:
            db.execute(delete(DemoVector).where(DemoVector.tenant_id == tenant_id,
                                                DemoVector.document_id == document_id))

    def search(self, db: Session, tenant_id: str, allowed_doc_ids: list[str],
               vector: list[float], limit: int) -> list[tuple[str, float]]:
        if not allowed_doc_ids:
            return []
        if self.client is not None:
            # Restrict candidate vectors BEFORE similarity scoring, not after the search.
            m = self.models
            result = self.client.query_points(
                collection_name=settings.qdrant_collection, query=vector, limit=limit,
                query_filter=m.Filter(must=[
                    m.FieldCondition(key="tenant_id", match=m.MatchValue(value=tenant_id)),
                    m.FieldCondition(key="document_id", match=m.MatchAny(any=allowed_doc_ids))]))
            return [(str(point.id), float(point.score)) for point in result.points]
        entries = db.scalars(select(DemoVector).where(
            DemoVector.tenant_id == tenant_id,
            DemoVector.document_id.in_(allowed_doc_ids))).all()
        results = []
        for entry in entries:
            other = json.loads(entry.vector_json)
            # Offline lexical vectors are normalized. Qdrant handles cosine in live mode.
            score = sum(x*y for x, y in zip(vector, other))
            results.append((entry.chunk_id, score))
        return sorted(results, key=lambda x: (-x[1], x[0]))[:limit]
