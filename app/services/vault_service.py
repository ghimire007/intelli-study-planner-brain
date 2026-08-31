"""Storing, replacing and deleting the API keys students bring.

The one invariant worth stating plainly: a readable key enters this module as an
argument and leaves it only as ciphertext or as a network call to the provider.
Nothing here returns, logs, or persists one.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.core.crypto import DecryptionError, SealedSecret, VaultConfigurationError, last4
from app.llm.keyshape import mismatch_reason
from app.llm.registry import (
    DEFAULT_MODEL_BY_PROVIDER,
    PROVIDER_CONSOLE_URLS,
    PROVIDER_LABELS,
    Provider,
    models_for,
)
from app.llm.verify import KeyRejected, VerificationUnavailable, verify_key
from app.models.auth import User
from app.models.credential import (
    AuditAction,
    CredentialStatus,
    LLMCredential,
    LLMCredentialAudit,
)
from app.services.secret_store import (
    SecretStoreError,
    StoredSecret,
    active_store,
    store_for,
)
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

#: Don't write last_used_at on every single turn of a conversation.
_LAST_USED_GRANULARITY = timedelta(minutes=5)


class VaultError(Exception):
    """Something the student can fix — surfaced to them verbatim."""


class KeyNotFound(VaultError):
    pass


class DuplicateLabel(VaultError):
    pass


def sealed_of(credential: LLMCredential) -> SealedSecret:
    return SealedSecret(
        ciphertext=credential.key_ciphertext,
        nonce=credential.nonce,
        dek_wrapped=credential.dek_wrapped,
        dek_nonce=credential.dek_nonce,
        key_version=credential.key_version,
    )


def apply_sealed(credential: LLMCredential, sealed: SealedSecret) -> None:
    credential.key_ciphertext = sealed.ciphertext
    credential.nonce = sealed.nonce
    credential.dek_wrapped = sealed.dek_wrapped
    credential.dek_nonce = sealed.dek_nonce
    credential.key_version = sealed.key_version


def apply_stored(credential: LLMCredential, stored: StoredSecret) -> None:
    """Record where this credential's secret ended up."""
    credential.backend = stored.backend
    credential.secret_ref = stored.secret_ref
    if stored.sealed is not None:
        apply_sealed(credential, stored.sealed)


async def reveal(credential: LLMCredential) -> str:
    """Fetch one key in the clear. Callers must keep the result request-scoped."""
    return await store_for(credential.backend).get(credential)


class VaultService:
    def __init__(self, db: AsyncSession, *, actor_ip: str | None = None) -> None:
        self._db = db
        self._ip = actor_ip

    # ── reads ────────────────────────────────────────────────────────────────

    async def list_keys(self, user: User) -> list[LLMCredential]:
        rows = await self._db.scalars(
            select(LLMCredential)
            .where(LLMCredential.user_id == user.id)
            .order_by(
                LLMCredential.provider,
                LLMCredential.is_default.desc(),
                LLMCredential.created_at,
            )
        )
        return list(rows)

    async def get_key(self, user: User, credential_id: uuid.UUID) -> LLMCredential:
        credential = await self._db.get(LLMCredential, credential_id)
        if credential is None or credential.user_id != user.id:
            # 404 rather than 403 — don't confirm that somebody else's id exists.
            raise KeyNotFound("No such key.")
        return credential

    async def providers_overview(self, user: User) -> dict[Provider, dict]:
        credentials = await self.list_keys(user)
        overview: dict[Provider, dict] = {}
        for provider in Provider:
            owned = [c for c in credentials if c.provider == provider.value]
            usable = [c for c in owned if c.status == CredentialStatus.ACTIVE.value]
            overview[provider] = {
                "provider": provider.value,
                "label": PROVIDER_LABELS[provider],
                "console_url": PROVIDER_CONSOLE_URLS[provider],
                "models": [
                    {"name": spec.name, "label": spec.label, "priced": spec.pricing is not None}
                    for spec in models_for(provider)
                ],
                "default_model": DEFAULT_MODEL_BY_PROVIDER[provider],
                "key_count": len(owned),
                "has_usable_key": bool(usable),
            }
        return overview

    # ── writes ───────────────────────────────────────────────────────────────

    async def create_key(
        self,
        user: User,
        *,
        provider: Provider,
        api_key: str,
        label: str | None,
        make_default: bool,
        verify: bool,
    ) -> LLMCredential:
        self._reject_obvious_mismatch(provider, api_key)
        verified_at = await self._verify(provider, api_key) if verify else None

        # Ask this *before* adding the new row: a query would autoflush it, and the
        # "first key for a provider" check would then always find itself.
        is_first = (
            await self._db.scalar(
                select(LLMCredential.id).where(
                    LLMCredential.user_id == user.id,
                    LLMCredential.provider == provider.value,
                )
            )
        ) is None

        store = active_store()
        credential = LLMCredential(
            id=uuid.uuid4(),
            user_id=user.id,
            provider=provider.value,
            label=label or self._auto_label(provider),
            last4=last4(api_key),
            status=CredentialStatus.ACTIVE.value,
            last_verified_at=verified_at,
            is_default=False,
            backend=store.name,
        )
        # Store the secret before the row is written: ck_llm_credential_secret_present
        # refuses a row that names no location for its key, and CHECK constraints
        # cannot be deferred in Postgres. A duplicate label below cleans up after us.
        try:
            apply_stored(credential, await store.put(credential, api_key))
        except (SecretStoreError, VaultConfigurationError) as exc:
            raise VaultError(str(exc)) from exc

        self._db.add(credential)
        # Flush now. Otherwise the next query autoflushes this INSERT from inside
        # _clear_defaults, and a duplicate label surfaces there as an uncatchable
        # IntegrityError instead of a 409.
        try:
            await self._flush_or_duplicate(
                f"You already have a key labelled {credential.label!r}."
            )
        except Exception:
            await self._forget_quietly(credential)
            raise

        # The first key for a provider is the default whether or not they asked.
        if make_default or is_first:
            await self._clear_defaults(user.id, provider.value)
            credential.is_default = True

        self._audit(user, credential, AuditAction.CREATED, f"…{credential.last4}")
        try:
            await self._commit(f"You already have a key labelled {credential.label!r}.")
        except Exception:
            # The secret is already written; don't strand it without its row.
            await self._forget_quietly(credential)
            raise
        return credential

    async def update_key(
        self,
        user: User,
        credential_id: uuid.UUID,
        *,
        api_key: str | None,
        label: str | None,
        make_default: bool | None,
        verify: bool,
    ) -> LLMCredential:
        credential = await self.get_key(user, credential_id)
        provider = Provider(credential.provider)

        if api_key is not None:
            self._reject_obvious_mismatch(provider, api_key)
            verified_at = await self._verify(provider, api_key) if verify else None
            # Rotate through whichever backend already holds this row's secret,
            # not the currently configured one — the row may predate a switch.
            try:
                apply_stored(
                    credential, await store_for(credential.backend).put(credential, api_key)
                )
            except (SecretStoreError, VaultConfigurationError) as exc:
                await self._db.rollback()
                raise VaultError(str(exc)) from exc
            credential.last4 = last4(api_key)
            # A replaced key clears an earlier rejection.
            credential.status = CredentialStatus.ACTIVE.value
            credential.last_verified_at = verified_at
            self._audit(user, credential, AuditAction.ROTATED, f"…{credential.last4}")

        if label is not None and label != credential.label:
            credential.label = label
            await self._flush_or_duplicate(f"You already have a key labelled {label!r}.")
            self._audit(user, credential, AuditAction.RELABELLED, label)

        if make_default:
            await self._clear_defaults(user.id, credential.provider, keep=credential.id)
            credential.is_default = True
            self._audit(user, credential, AuditAction.DEFAULT_SET)

        await self._commit(f"You already have a key labelled {label!r}.")
        return credential

    async def delete_key(self, user: User, credential_id: uuid.UUID) -> None:
        credential = await self.get_key(user, credential_id)
        was_default = credential.is_default
        provider = credential.provider
        self._audit(user, credential, AuditAction.DELETED, f"…{credential.last4}")
        # Remove the secret first. If this fails we stop, rather than dropping the
        # row and leaving an unreferenced key sitting in the backend forever.
        try:
            await store_for(credential.backend).delete(credential)
        except SecretStoreError as exc:
            raise VaultError(f"{exc} The key was not deleted.") from exc
        await self._db.delete(credential)
        await self._db.flush()

        if was_default:
            await self._promote_replacement(user.id, provider)
        await self._db.commit()

    async def verify_stored_key(self, user: User, credential_id: uuid.UUID) -> tuple[bool, str]:
        """Re-check a stored key, updating its status. Returns (ok, message)."""
        credential = await self.get_key(user, credential_id)
        provider = Provider(credential.provider)
        try:
            api_key = await reveal(credential)
        except (DecryptionError, VaultConfigurationError):
            return False, (
                "This key can no longer be decrypted on this server. "
                "Replace it with a fresh one."
            )
        except SecretStoreError as exc:
            return False, str(exc)
        try:
            await verify_key(provider, api_key)
        except KeyRejected as exc:
            credential.status = CredentialStatus.INVALID.value
            self._audit(user, credential, AuditAction.REJECTED, str(exc)[:255])
            await self._db.commit()
            return False, str(exc)
        except VerificationUnavailable as exc:
            await self._db.commit()
            return False, str(exc)

        credential.status = CredentialStatus.ACTIVE.value
        credential.last_verified_at = datetime.now(timezone.utc)
        self._audit(user, credential, AuditAction.VERIFIED)
        await self._db.commit()
        return True, f"{PROVIDER_LABELS[provider]} accepted this key."

    async def mark_rejected(self, credential_id: uuid.UUID, detail: str) -> None:
        """Flip a credential to `invalid` after the provider refused it mid-chat."""
        credential = await self._db.get(LLMCredential, credential_id)
        if credential is None:
            return
        credential.status = CredentialStatus.INVALID.value
        self._db.add(
            LLMCredentialAudit(
                user_id=credential.user_id,
                credential_id=credential.id,
                provider=credential.provider,
                action=AuditAction.REJECTED.value,
                detail=detail[:255],
                actor_ip=self._ip,
            )
        )
        await self._db.commit()

    async def touch_used(self, credential_id: uuid.UUID) -> None:
        """Record that a key was used, at five-minute granularity.

        Per-turn precision isn't worth a write on every message; "used recently"
        is all the settings page needs.
        """
        cutoff = datetime.now(timezone.utc) - _LAST_USED_GRANULARITY
        await self._db.execute(
            update(LLMCredential)
            .where(
                LLMCredential.id == credential_id,
                (LLMCredential.last_used_at.is_(None)) | (LLMCredential.last_used_at < cutoff),
            )
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await self._db.commit()

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _reject_obvious_mismatch(provider: Provider, api_key: str) -> None:
        reason = mismatch_reason(provider, api_key)
        if reason:
            raise VaultError(reason)

    @staticmethod
    async def _verify(provider: Provider, api_key: str) -> datetime:
        try:
            await verify_key(provider, api_key)
        except KeyRejected as exc:
            raise VaultError(str(exc)) from exc
        except VerificationUnavailable as exc:
            raise VaultError(f"{exc} Your key was not saved — please try again.") from exc
        return datetime.now(timezone.utc)

    async def _clear_defaults(
        self, user_id: uuid.UUID, provider: str, *, keep: uuid.UUID | None = None
    ) -> None:
        stmt = update(LLMCredential).where(
            LLMCredential.user_id == user_id,
            LLMCredential.provider == provider,
            LLMCredential.is_default.is_(True),
        )
        if keep is not None:
            stmt = stmt.where(LLMCredential.id != keep)
        await self._db.execute(stmt.values(is_default=False))
        # Flush before the caller sets a new default, or the partial unique index
        # sees two defaults inside the same statement batch.
        await self._db.flush()

    async def _promote_replacement(self, user_id: uuid.UUID, provider: str) -> None:
        """Deleting the default leaves the provider unusable — promote the next key."""
        replacement = await self._db.scalar(
            select(LLMCredential)
            .where(
                LLMCredential.user_id == user_id,
                LLMCredential.provider == provider,
                LLMCredential.status == CredentialStatus.ACTIVE.value,
            )
            .order_by(LLMCredential.created_at)
            .limit(1)
        )
        if replacement is not None:
            replacement.is_default = True

    def _audit(
        self,
        user: User,
        credential: LLMCredential,
        action: AuditAction,
        detail: str | None = None,
    ) -> None:
        self._db.add(
            LLMCredentialAudit(
                user_id=user.id,
                credential_id=credential.id,
                provider=credential.provider,
                action=action.value,
                detail=detail,
                actor_ip=self._ip,
            )
        )

    async def _flush_or_duplicate(self, duplicate_message: str) -> None:
        """Write pending rows now, turning a label clash into a 409 we control."""
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise DuplicateLabel(duplicate_message) from exc

    async def _commit(self, duplicate_message: str) -> None:
        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            raise DuplicateLabel(duplicate_message) from exc

    @staticmethod
    async def _forget_quietly(credential: LLMCredential) -> None:
        """Best-effort cleanup of a secret whose row never made it."""
        try:
            await store_for(credential.backend).delete(credential)
        except SecretStoreError:
            pass  # nothing further we can do from here

    @staticmethod
    def _auto_label(provider: Provider) -> str:
        return f"My {PROVIDER_LABELS[provider]} key"
