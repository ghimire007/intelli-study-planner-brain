"""Where a student's API key is actually kept.

Two backends, chosen by ``SECRET_BACKEND``:

* ``local``     — sealed into the ``llm_credential`` row itself by app/core/crypto.py.
                  No network on the chat path; the master key never leaves the host.
* ``infisical`` — held by Infisical. The row keeps only metadata (provider, label,
                  last4, is_default) plus ``secret_ref``, the name of the secret.

Every row records the backend that holds its secret, so a table may contain both
and switching the setting only changes where *new* keys go.

Whichever backend is in use, the contract is the same: a readable key enters
``put`` and leaves only from ``get``, inside one request.
"""
from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.core.crypto import SealedSecret, build_aad, seal, unseal
from app.models.credential import LLMCredential

LOCAL = "local"
INFISICAL = "infisical"


class SecretStoreError(RuntimeError):
    """The backend could not store, fetch or delete the secret."""


@dataclass(frozen=True)
class StoredSecret:
    """What the credential row must record so the secret can be found again."""

    backend: str
    sealed: SealedSecret | None = None
    secret_ref: str | None = None


class SecretStore(Protocol):
    name: str

    async def put(self, credential: LLMCredential, api_key: str) -> StoredSecret: ...
    async def get(self, credential: LLMCredential) -> str: ...
    async def delete(self, credential: LLMCredential) -> None: ...


def _aad(credential: LLMCredential) -> bytes:
    return build_aad(credential.user_id, credential.provider, credential.id)


class LocalEnvelopeStore:
    """Envelope encryption in the row — see app/core/crypto.py."""

    name = LOCAL

    async def put(self, credential: LLMCredential, api_key: str) -> StoredSecret:
        return StoredSecret(backend=LOCAL, sealed=seal(api_key, _aad(credential)))

    async def get(self, credential: LLMCredential) -> str:
        return unseal(
            SealedSecret(
                ciphertext=credential.key_ciphertext,
                nonce=credential.nonce,
                dek_wrapped=credential.dek_wrapped,
                dek_nonce=credential.dek_nonce,
                key_version=credential.key_version,
            ),
            _aad(credential),
        )

    async def delete(self, credential: LLMCredential) -> None:
        """Nothing to do — the secret goes with the row."""


def store_for(backend: str | None) -> SecretStore:
    """The store that holds one existing credential's secret."""
    if backend in (None, "", LOCAL):
        return LocalEnvelopeStore()
    if backend == INFISICAL:
        from app.services.infisical_store import InfisicalStore

        return InfisicalStore()
    raise SecretStoreError(f"Unknown secret backend {backend!r}")


def active_store() -> SecretStore:
    """The store new keys are written to."""
    return store_for(settings.SECRET_BACKEND)
