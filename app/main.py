from contextlib import asynccontextmanager

from fastapi import FastAPI

import logging

from app.core.database import connect, disconnect

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    yield
    await disconnect()


app = FastAPI(title="IntelliStudy Planner Brain", lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Hello World"}
