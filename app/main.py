import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.v1.router import router as api_router
from app.core.checkpointer import connect_checkpointer, disconnect_checkpointer
from app.core.config import settings
from app.core.database import connect, disconnect

logger = logging.getLogger("uvicorn")
STATIC_INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    await connect_checkpointer()
    yield
    await disconnect_checkpointer()
    await disconnect()


app = FastAPI(
    title="IntelliStudy Planner Brain",
    description=(
        "AI-powered study plan advisor for the University of Wollongong. "
        "Paste your SOLS enrolment, get handbook-aware advice via LLM."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.api_route("/health", methods=["GET", "HEAD"], tags=["health"])
async def health():
    """Liveness probe for deploy platforms."""
    return {"status": "ok"}


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def ui():
    if STATIC_INDEX.is_file():
        return HTMLResponse(
            STATIC_INDEX.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        {
            "service": "intelli-study-planner-brain",
            "status": "ok",
            "docs": "/docs",
            "health": "/health",
        }
    )
