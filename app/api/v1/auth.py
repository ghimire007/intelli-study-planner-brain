from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.auth import LoginRequest, RegisterRequest, UserOut
from app.services.auth_service import AuthService

router = APIRouter()


def _get_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.AUTH_SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="none",
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    service: AuthService = Depends(_get_service),
):
    try:
        user, token = await service.register(body.email, body.password, body.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _set_session_cookie(response, token)
    return user


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest,
    response: Response,
    service: AuthService = Depends(_get_service),
):
    try:
        user, token = await service.login(body.email, body.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    _set_session_cookie(response, token)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session_token: str | None = Cookie(
        default=None, alias=settings.AUTH_COOKIE_NAME
    ),
    service: AuthService = Depends(_get_service),
):
    await service.logout(session_token)
    response.delete_cookie(
        settings.AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
    )


@router.get("/me", response_model=UserOut)
async def me(
    session_token: str | None = Cookie(
        default=None, alias=settings.AUTH_COOKIE_NAME
    ),
    service: AuthService = Depends(_get_service),
):
    user = await service.authenticate(session_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user
