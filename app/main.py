from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.core.database import connect, disconnect
from app.api.v1.router import router as api_router

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    yield
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
app.include_router(api_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def ui():
    with open("static/index.html") as f:
        content = f.read()
    return HTMLResponse(content=content, headers={"Cache-Control": "no-store"})
