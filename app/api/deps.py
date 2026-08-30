"""Shared FastAPI dependencies.

``get_current_user`` was inlined in the auth router; the vault and chat routes
need the same resolution, and per-user key loading is meaningless without it.
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyCookie
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.auth import User
from app.services.auth_service import AuthService

#: Declared so /docs marks protected routes with a padlock and the OpenAPI schema
#: is honest about how auth works. There is nothing to paste into Swagger's
#: Authorize box: the browser sets this cookie for you when you call
#: /auth/register or /auth/login, and sends it on every later call from that page.
cookie_scheme = APIKeyCookie(
    name=settings.AUTH_COOKIE_NAME,
    auto_error=False,
    scheme_name="Session cookie",
    description=(
        "Set automatically by POST /api/v1/auth/register or /login. "
        "Nothing to paste — just call one of those first."
    ),
)


async def get_current_user(
    session_token: str | None = Depends(cookie_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await AuthService(db).authenticate(session_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue.",
        )
    return user


def client_ip(request: Request) -> str | None:
    """Best-effort caller IP for the audit trail.

    Render (like most PaaS) terminates TLS at a proxy, so the socket address is
    the proxy's — take the first hop of X-Forwarded-For when it is present.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else None
