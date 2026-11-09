"""Environment-driven application settings without implicit production fallbacks."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./talentatlas.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-change-before-deployment")
    jwt_minutes: int = int(os.getenv("JWT_MINUTES", "90"))
    ai_mode: str = os.getenv("AI_MODE", "demo").lower()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    chat_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "1536"))
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "talentatlas_chunks_v1")
    redis_url: str = os.getenv("REDIS_URL", "")
    upload_dir: str = os.getenv("UPLOAD_DIR", "./uploads")
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:8000")

    def check(self):
        if self.ai_mode not in ("demo", "live"):
            raise RuntimeError("AI_MODE must be demo or live")
        if self.ai_mode == "live":
            if len(self.jwt_secret) < 32 or self.jwt_secret.startswith("dev-"):
                raise RuntimeError("Live mode requires a strong JWT_SECRET")
            if not self.openai_api_key:
                raise RuntimeError("Live mode requires OPENAI_API_KEY")
            if not self.redis_url:
                raise RuntimeError("Live mode requires REDIS_URL")


settings = Settings()
