"""The student's key settings: add, rename, replace, delete, re-check.

Note what is missing: there is no endpoint that returns a stored key. A key goes
in and never comes back out — the most any response reveals is its last four
characters.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import RateLimiter
from app.llm.registry import Provider, coerce_provider
from app.models.auth import User
from app.schemas.vault import (
    CreateKeyIn,
    KeyOut,
    ProvidersOut,
    UpdateKeyIn,
    VerifyKeyOut,
)
from app.services.vault_service import DuplicateLabel, KeyNotFound, VaultError, VaultService

router = APIRouter()

_ONE_HOUR = 3600
# Without these, the endpoints are a free key-validity oracle for anyone holding
# a list of stolen keys.
_write_limiter = RateLimiter(settings.VAULT_WRITE_LIMIT_PER_HOUR, _ONE_HOUR)
_verify_limiter = RateLimiter(settings.VAULT_VERIFY_LIMIT_PER_HOUR, _ONE_HOUR)


def _get_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> VaultService:
    return VaultService(db, actor_ip=client_ip(request))


def _throttle(limiter: RateLimiter, user: User, what: str) -> None:
    if not limiter.allow(str(user.id)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many {what} in the last hour. Try again later.",
        )


def _provider_or_422(value: str) -> Provider:
    try:
        return coerce_provider(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/providers", response_model=ProvidersOut)
async def list_providers(
    user: User = Depends(get_current_user),
    service: VaultService = Depends(_get_service),
):
    """Which providers exist, which models they run, and where this student stands."""
    overview = await service.providers_overview(user)
    return ProvidersOut(
        providers=list(overview.values()),
        default_model=settings.GEMINI_MODEL,
        system_fallback_enabled=settings.ALLOW_SYSTEM_FALLBACK_KEY,
    )


@router.get("", response_model=list[KeyOut])
async def list_keys(
    user: User = Depends(get_current_user),
    service: VaultService = Depends(_get_service),
):
    return await service.list_keys(user)


@router.post("", response_model=KeyOut, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: CreateKeyIn,
    user: User = Depends(get_current_user),
    service: VaultService = Depends(_get_service),
):
    _throttle(_write_limiter, user, "key changes")
    provider = _provider_or_422(body.provider)
    try:
        return await service.create_key(
            user,
            provider=provider,
            api_key=body.api_key,
            label=body.label,
            make_default=body.make_default,
            verify=settings.VAULT_VERIFY_ON_WRITE,
        )
    except DuplicateLabel as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except VaultError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.patch("/{credential_id}", response_model=KeyOut)
async def update_key(
    credential_id: uuid.UUID,
    body: UpdateKeyIn,
    user: User = Depends(get_current_user),
    service: VaultService = Depends(_get_service),
):
    _throttle(_write_limiter, user, "key changes")
    try:
        return await service.update_key(
            user,
            credential_id,
            api_key=body.api_key,
            label=body.label,
            make_default=body.make_default,
            verify=settings.VAULT_VERIFY_ON_WRITE,
        )
    except KeyNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateLabel as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except VaultError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    credential_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: VaultService = Depends(_get_service),
):
    try:
        await service.delete_key(user, credential_id)
    except KeyNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{credential_id}/verify", response_model=VerifyKeyOut)
async def verify_key(
    credential_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: VaultService = Depends(_get_service),
):
    """Re-check a key against its provider — for one that went `invalid` mid-chat."""
    _throttle(_verify_limiter, user, "key checks")
    try:
        ok, detail = await service.verify_stored_key(user, credential_id)
        credential = await service.get_key(user, credential_id)
    except KeyNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return VerifyKeyOut(id=credential.id, status=credential.status, verified=ok, detail=detail)
