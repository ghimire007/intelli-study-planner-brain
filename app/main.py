from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.core.database import connect, disconnect
from app.core.checkpointer import connect_checkpointer, disconnect_checkpointer
from app.api.v1.router import router as api_router

logger = logging.getLogger("uvicorn")


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
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def ui():
    with open("static/index.html") as f:
        content = f.read()
    return HTMLResponse(content=content, headers={"Cache-Control": "no-store"})
