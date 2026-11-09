"""Optional Redis TTL cache: never broadens document authorization."""
import json
from .helpers import stable_digest
from ..config import settings


class Cache:
    def __init__(self):
        self.client = None
        if settings.redis_url:
            try:
                import redis
                self.client = redis.Redis.from_url(settings.redis_url,
                                                   socket_connect_timeout=0.5,
                                                   socket_timeout=0.5,
                                                   decode_responses=True)
            except ImportError:
                if settings.ai_mode == "live":
                    raise RuntimeError("Install redis package for live mode")

    def get(self, namespace: str, *parts):
        if self.client is None:
            return None
        try:
            found = self.client.get(f"talentatlas:{namespace}:{stable_digest(*parts)}")
            return json.loads(found) if found else None
        except Exception:
            return None

    def set(self, namespace: str, data, *parts, ttl: int = 120):
        if self.client is not None:
            try:
                self.client.setex(f"talentatlas:{namespace}:{stable_digest(*parts)}",
                                  ttl, json.dumps(data))
            except Exception:
                pass
