import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.v1.router import router as api_router
from app.core.checkpointer import connect_checkpointer, disconnect_checkpointer
from app.core.config import settings
from app.core.crypto import vault_is_configured
from app.core.database import connect, disconnect

logger = logging.getLogger("uvicorn")
STATIC_INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"


def _log_cookie_state() -> None:
    problem = settings.cookie_misconfigured()
    if problem:
        logger.error(problem)
    else:
        logger.info(
            "Session cookie: SameSite=%s, Secure=%s",
            settings.AUTH_COOKIE_SAMESITE,
            settings.AUTH_COOKIE_SECURE,
        )


def _log_vault_state() -> None:
    """Fail loudly at boot rather than at the first student who adds a key."""
    if vault_is_configured():
        logger.info("Key vault ready (master key v%s)", settings.SECRETS_ACTIVE_KEY_VERSION)
    else:
        logger.warning(
            "SECRETS_MASTER_KEYS is not set — students cannot save their own API keys. "
            "Generate one: python -c "
            "\"import base64,os;print(base64.b64encode(os.urandom(32)).decode())\""
        )
    if not settings.ALLOW_SYSTEM_FALLBACK_KEY:
        logger.info(
            "System fallback off — students must add their own key before chatting"
        )
    elif settings.GEMINI_API_KEY:
        logger.info(
            "System fallback on — students with no Gemini key of their own will "
            "use this project's quota"
        )
    else:
        # The setting promises a fallback we cannot actually provide, so chat
        # will 409 for keyless students exactly as if it were switched off.
        logger.warning(
            "ALLOW_SYSTEM_FALLBACK_KEY is on but GEMINI_API_KEY is empty — there is "
            "no key to fall back to, so students without their own will be refused"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    await connect_checkpointer()
    _log_vault_state()
    _log_cookie_state()
    yield
    await disconnect_checkpointer()
    await disconnect()


app = FastAPI(
    title="IntelliStudy Planner Brain",
    description=(
        "AI-powered study plan advisor for the University of Wollongong. "
        "Paste your SOLS enrolment, get handbook-aware advice via LLM.\n\n"
        "### Signing in from this page\n\n"
        "Endpoints with a padlock need a session. **Call `POST /api/v1/auth/register` "
        "or `/login` first** — your browser stores the session cookie and sends it on "
        "every later call from this page. There is nothing to paste into Authorize; "
        "a cookie is set by the server, not by Swagger. `GET /api/v1/auth/me` "
        "returning 200 confirms you are signed in.\n\n"
        "### Trying the key vault\n\n"
        "`POST /api/v1/keys` verifies the key against the real provider before "
        "storing it, so a made-up key is correctly rejected with 422. Set "
        "`VAULT_VERIFY_ON_WRITE=false` to exercise the storage path with fake keys."
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
@app.middleware("http")
async def log_incoming_auth_state(request: Request, call_next):
    if request.url.path.startswith("/api/v1/chat") or request.url.path.startswith("/api/v1/auth/me"):
        client_ip = request.client.host if request.client else "unknown"
        cookies = request.cookies
        has_session = settings.AUTH_COOKIE_NAME in cookies
        
        logger.info(
            f"[AUTH DEBUG] {request.method} {request.url.path} | Client IP: {client_ip} | "
            f"Has Cookie ({settings.AUTH_COOKIE_NAME}): {has_session} | "
            f"All Cookies: {list(cookies.keys())}"
        )

    response = await call_next(request)
    return response
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
