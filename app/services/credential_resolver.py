"""Pick the key a chat turn should run on.

The order:

    1. the credential pinned on this chat session
    2. the student's default key for the model's provider
    3. any other active key they hold for that provider
    4. the project's own key — only when ALLOW_SYSTEM_FALLBACK_KEY is on
    5. otherwise a 409 telling them which provider needs a key

Step 1 is what keeps a long conversation on one key after the student changes
their default. Step 4 exists for demos and CI and is off by default, so students
spend their own quota rather than the project's.
"""
import uuid

from app.core.config import settings
from app.core.crypto import DecryptionError, VaultConfigurationError
from app.llm.config import LLMConfig
from app.llm.registry import (
    DEFAULT_MODEL_BY_PROVIDER,
    PROVIDER_LABELS,
    Provider,
    UnknownModelError,
    article_for,
    provider_for,
)
from app.models.auth import User
from app.models.credential import CredentialStatus, LLMCredential
from app.models.session import ChatSession
from app.services.secret_store import SecretStoreError
from app.services.vault_service import reveal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class NoCredentialError(Exception):
    """The student has no usable key for the provider this model needs."""

    def __init__(self, provider: Provider, invalid_only: bool = False) -> None:
        name = PROVIDER_LABELS[provider]
        if invalid_only:
            message = (
                f"Your {name} key was rejected the last time we used it. "
                f"Update it in your key settings to keep chatting."
            )
        else:
            message = (
                f"Add {article_for(provider)} {name} API key in your settings to use this model."
            )
        super().__init__(message)
        self.provider = provider


class CredentialUnreadable(Exception):
    """The stored key cannot be decrypted with the master keys this process has.

    Almost always an operator error: SECRETS_MASTER_KEYS was changed without
    re-sealing what it had encrypted, or an old version was dropped while rows
    were still sealed with it. Say so plainly, not as a 500.
    """


class CredentialResolver:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def resolve(
        self,
        user: User,
        *,
        requested_model: str | None = None,
        session: ChatSession | None = None,
    ) -> LLMConfig:
        model = requested_model or (session.model if session else None) or settings.GEMINI_MODEL
        try:
            provider = provider_for(model)
        except UnknownModelError as exc:
            raise ValueError(str(exc)) from exc

        candidates = await self._active_for(user.id, provider)

        # Nobody asked for this model by name and the student has no key for its
        # provider — if they have keys for exactly one other provider, use that
        # instead of telling them to go and buy a Gemini key.
        if not candidates and requested_model is None:
            switched = await self._only_other_provider(user.id, provider)
            if switched is not None:
                provider = switched
                model = DEFAULT_MODEL_BY_PROVIDER[provider]
                candidates = await self._active_for(user.id, provider)

        credential = self._choose(candidates, session)
        if credential is not None:
            try:
                api_key = await reveal(credential)
            except SecretStoreError as exc:
                # Infisical unreachable, or the secret was removed there.
                raise CredentialUnreadable(str(exc)) from exc
            except (DecryptionError, VaultConfigurationError) as exc:
                raise CredentialUnreadable(
                    f"Your {PROVIDER_LABELS[provider]} key can no longer be decrypted "
                    f"on this server. Re-enter it in your key settings."
                ) from exc
            return LLMConfig(
                provider=provider,
                model=model,
                api_key=api_key,
                credential_id=credential.id,
            )

        if (
            settings.ALLOW_SYSTEM_FALLBACK_KEY
            and provider is Provider.GEMINI
            and settings.GEMINI_API_KEY
        ):
            return LLMConfig(
                provider=provider,
                model=model,
                api_key=settings.GEMINI_API_KEY,
                credential_id=None,
            )

        raise NoCredentialError(provider, invalid_only=await self._has_any(user.id, provider))

    async def _active_for(self, user_id: uuid.UUID, provider: Provider) -> list[LLMCredential]:
        rows = await self._db.scalars(
            select(LLMCredential)
            .where(
                LLMCredential.user_id == user_id,
                LLMCredential.provider == provider.value,
                LLMCredential.status == CredentialStatus.ACTIVE.value,
            )
            .order_by(LLMCredential.is_default.desc(), LLMCredential.created_at)
        )
        return list(rows)

    async def _has_any(self, user_id: uuid.UUID, provider: Provider) -> bool:
        found = await self._db.scalar(
            select(LLMCredential.id).where(
                LLMCredential.user_id == user_id,
                LLMCredential.provider == provider.value,
            )
        )
        return found is not None

    async def _only_other_provider(
        self, user_id: uuid.UUID, exclude: Provider
    ) -> Provider | None:
        rows = await self._db.scalars(
            select(LLMCredential.provider)
            .where(
                LLMCredential.user_id == user_id,
                LLMCredential.provider != exclude.value,
                LLMCredential.status == CredentialStatus.ACTIVE.value,
            )
            .distinct()
        )
        providers = {p for p in rows}
        if len(providers) != 1:
            return None
        try:
            return Provider(providers.pop())
        except ValueError:
            return None

    @staticmethod
    def _choose(
        candidates: list[LLMCredential], session: ChatSession | None
    ) -> LLMCredential | None:
        if not candidates:
            return None
        pinned = session.credential_id if session else None
        if pinned is not None:
            for credential in candidates:
                if credential.id == pinned:
                    return credential
        # Already ordered default-first, then oldest.
        return candidates[0]
