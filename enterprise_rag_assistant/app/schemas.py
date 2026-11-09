from pydantic import BaseModel, Field
from typing import List

class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    user_id: str = Field(min_length=1, max_length=120)
    roles: List[str] = Field(default_factory=lambda: ["employee"])
    top_k: int = Field(default=5, ge=1, le=12)

class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]
    retrieval_count: int
    mode: str
