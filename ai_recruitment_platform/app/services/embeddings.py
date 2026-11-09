"""OpenAI embeddings via LangChain; offline mode uses lexical hash vectors only."""
import hashlib
import math
import re
from ..config import settings
from .cache import Cache


class Embedder:
    def __init__(self):
        self.cache = Cache()
        if settings.ai_mode == "live":
            try:
                from langchain_openai import OpenAIEmbeddings
            except ImportError as exc:
                raise RuntimeError("Install langchain-openai for live embeddings") from exc
            self.provider = OpenAIEmbeddings(
                api_key=settings.openai_api_key,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimension,
            )
            self.dimension = settings.embedding_dimension
        else:
            self.provider = None
            self.dimension = 256

    def embed(self, text: str, tenant_id: str) -> list[float]:
        cached = self.cache.get("embedding", tenant_id, settings.ai_mode,
                                settings.embedding_model, text)
        if cached is not None:
            return cached
        if self.provider is not None:
            vector = self.provider.embed_query(text)
        else:
            # Deterministic lexical comparison is for offline demonstrations, NOT semantic embeddings.
            vector = [0.0] * self.dimension
            for term in re.findall(r"[a-z0-9][a-z0-9+#.\-]*", text.lower()):
                index = int.from_bytes(hashlib.blake2b(term.encode(), digest_size=8).digest(), "big") % self.dimension
                vector[index] += 1.0
            magnitude = math.sqrt(sum(v*v for v in vector)) or 1.0
            vector = [v/magnitude for v in vector]
        self.cache.set("embedding", vector, tenant_id, settings.ai_mode,
                       settings.embedding_model, text, ttl=60*60)
        return vector

    def embed_many(self, texts: list[str], tenant_id: str) -> list[list[float]]:
        """Batch remote document embeddings; preserve per-text tenant-scoped cache."""
        if self.provider is None:
            return [self.embed(t, tenant_id) for t in texts]
        result: list[list[float] | None] = [None] * len(texts)
        outstanding: list[tuple[int, str]] = []
        for i, source in enumerate(texts):
            cached = self.cache.get("embedding", tenant_id, settings.ai_mode,
                                    settings.embedding_model, source)
            if cached is not None:
                result[i] = cached
            else:
                outstanding.append((i, source))
        for start in range(0, len(outstanding), 64):
            batch = outstanding[start:start+64]
            embeddings = self.provider.embed_documents([t for _, t in batch])
            if len(embeddings) != len(batch):
                raise RuntimeError("Embedding provider returned incorrect batch size")
            for (i, original), vec in zip(batch, embeddings):
                if len(vec) != self.dimension:
                    raise RuntimeError("Embedding dimensions do not match configured collection")
                result[i] = vec
                self.cache.set("embedding", vec, tenant_id, settings.ai_mode,
                               settings.embedding_model, original, ttl=3600)
        return [vec for vec in result if vec is not None]
