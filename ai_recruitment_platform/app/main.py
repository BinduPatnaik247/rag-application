"""FastAPI entrypoint. Demo auto-creates local tables; live uses Alembic migrations."""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .db import Base, engine
from . import models  # noqa: F401: register tables
from .api import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.check()
    if settings.ai_mode == "demo":
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="TalentAtlas AI Recruitment", version="1.0.0", lifespan=lifespan,
              description="Permission-aware document search and human-reviewed recruitment workflows")
app.add_middleware(CORSMiddleware,
                   allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
                   allow_credentials=True,
                   allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type"])
app.include_router(router)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
