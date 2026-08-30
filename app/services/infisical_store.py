"""Keep students' API keys in Infisical rather than in our own table.

One secret per credential, named ``LLM_CRED_<credential id, hex>``, in the project
and environment named by settings. The ``llm_credential`` row still owns everything
else — who it belongs to, which provider, the label, last4, is_default, status —
so ownership, the default index, the resolution ladder and the audit trail are
unchanged. Only the secret material moves.

**What Infisical actually holds is ciphertext, not keys.** Every value is sealed
by app/core/crypto.py first and stored as a ``v1.…`` token, bound by AAD to the
credential row it belongs to. Two independent things are therefore needed to read
a student's key: access to the Infisical project, *and* ``SECRETS_MASTER_KEYS``,
which never leaves this server. A leaked machine identity yields blobs; a leaked
master key with no Infisical access yields nothing.

That also means a secret moved between credentials inside Infisical will not
decrypt, and that ``SECRETS_MASTER_KEYS`` is required on this backend too —
losing it makes every stored key unrecoverable, exactly as with the local one.

Two more consequences worth being deliberate about:

* **Latency.** Every chat turn makes an HTTPS call to Infisical to read the key.
  We cache the auth token, never the secrets: caching plaintext keys in process
  memory across requests would undo the request-scoped guarantee the rest of the
  design rests on.
* **Availability.** If Infisical is unreachable, students with a stored key
  cannot chat. It surfaces as a 409 naming Infisical, not a generic 502.
"""
import asyncio
import logging
import time
import uuid

import httpx
from app.core.config import settings
from app.core.crypto import build_aad, from_token, seal, to_token, unseal
from app.models.credential import LLMCredential
from app.services.secret_store import INFISICAL, SecretStoreError, StoredSecret

logger = logging.getLogger("uvicorn")

_LOGIN_PATH = "/api/v1/auth/universal-auth/login"
_SECRET_PATH = "/api/v3/secrets/raw"
# Refresh well before the token actually lapses, so a long request can't straddle it.
_TOKEN_SAFETY_MARGIN = 300.0


def secret_name(credential_id: uuid.UUID) -> str:
    """Infisical secret keys are [A-Z0-9_], so a bare UUID will not do."""
    return f"LLM_CRED_{credential_id.hex.upper()}"


def _aad(credential: LLMCredential) -> bytes:
    """Bind the ciphertext to the row it belongs to, exactly as the local store does.

    So a secret moved between credentials inside Infisical fails to decrypt,
    rather than quietly authenticating somebody else's account.
    """
    return build_aad(credential.user_id, credential.provider, credential.id)


def _already_exists(status: int, payload: dict) -> bool:
    """Did a create fail only because the secret is already there?

    Infisical reports this as 400 with a message, not as a 409, so the status
    code alone is not enough to tell a rotation from a real failure.
    """
    if status not in (400, 409):
        return False
    message = str(payload.get("message") or payload.get("error") or "").lower()
    return "already exist" in message


class _TokenCache:
    """One machine-identity token per process, refreshed on expiry."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self, client: httpx.AsyncClient, force: bool = False) -> str:
        async with self._lock:
            if not force and self._token and time.monotonic() < self._expires_at:
                return self._token
            response = await client.post(
                _LOGIN_PATH,
                json={
                    "clientId": settings.INFISICAL_CLIENT_ID,
                    "clientSecret": settings.INFISICAL_CLIENT_SECRET,
                },
            )
            if response.status_code != 200:
                raise SecretStoreError(
                    f"Infisical rejected the machine identity ({response.status_code}). "
                    "Check INFISICAL_CLIENT_ID and INFISICAL_CLIENT_SECRET."
                )
            body = response.json()
            self._token = body["accessToken"]
            lifetime = float(body.get("expiresIn") or 3600)
            self._expires_at = time.monotonic() + max(lifetime - _TOKEN_SAFETY_MARGIN, 60.0)
            logger.info("Infisical machine identity authenticated")
            return self._token

    def clear(self) -> None:
        self._token = None
        self._expires_at = 0.0


_tokens = _TokenCache()


class InfisicalStore:
    name = INFISICAL

    def __init__(self) -> None:
        if not settings.infisical_configured():
            raise SecretStoreError(
                "SECRET_BACKEND=infisical needs INFISICAL_CLIENT_ID, "
                "INFISICAL_CLIENT_SECRET and INFISICAL_PROJECT_ID."
            )

    # ── the store contract ───────────────────────────────────────────────────

    async def put(self, credential: LLMCredential, api_key: str) -> StoredSecret:
        """Seal the key, then create or overwrite the secret holding the ciphertext."""
        name = credential.secret_ref or secret_name(credential.id)
        sealed = seal(api_key, _aad(credential))
        body = self._scope() | {"secretValue": to_token(sealed)}

        status, payload = await self._call("POST", f"{_SECRET_PATH}/{name}", json=body)
        if _already_exists(status, payload):
            # Infisical answers a repeat create with 400 "Secret already exists",
            # not the 409 the status code would suggest — so match on the message
            # as well, or every rotation fails.
            status, payload = await self._call("PATCH", f"{_SECRET_PATH}/{name}", json=body)
        if status >= 400:
            raise SecretStoreError(self._explain("store", status, payload))
        return StoredSecret(backend=INFISICAL, secret_ref=name)

    async def get(self, credential: LLMCredential) -> str:
        name = credential.secret_ref or secret_name(credential.id)
        status, payload = await self._call(
            "GET", f"{_SECRET_PATH}/{name}", params=self._scope()
        )
        if status == 404:
            raise SecretStoreError(
                "This key is no longer in Infisical — it may have been deleted there. "
                "Re-enter it in your key settings."
            )
        if status >= 400:
            raise SecretStoreError(self._explain("read", status, payload))
        try:
            stored = payload["secret"]["secretValue"]
        except (KeyError, TypeError) as exc:
            raise SecretStoreError("Infisical returned a secret in an unexpected shape") from exc

        sealed = from_token(stored)
        if sealed is None:
            # Written before sealing was introduced: the value is the key itself.
            # Kept readable so nobody is locked out; PATCH it to seal it.
            logger.warning(
                "Credential %s is stored unsealed in Infisical — replace its value to seal it",
                credential.id,
            )
            return stored
        return unseal(sealed, _aad(credential))

    async def delete(self, credential: LLMCredential) -> None:
        name = credential.secret_ref or secret_name(credential.id)
        status, payload = await self._call(
            "DELETE", f"{_SECRET_PATH}/{name}", json=self._scope()
        )
        # A secret that is already gone is a success for our purposes.
        if status >= 400 and status != 404:
            raise SecretStoreError(self._explain("delete", status, payload))

    # ── plumbing ─────────────────────────────────────────────────────────────

    @staticmethod
    def _scope() -> dict:
        return {
            "workspaceId": settings.INFISICAL_PROJECT_ID,
            "environment": settings.INFISICAL_ENVIRONMENT,
            "secretPath": settings.INFISICAL_SECRET_PATH,
        }

    async def _call(self, method: str, path: str, **kwargs) -> tuple[int, dict]:
        """One authenticated request, retried once after a fresh login on 401."""
        try:
            async with httpx.AsyncClient(
                base_url=settings.INFISICAL_HOST,
                timeout=settings.INFISICAL_TIMEOUT_SECONDS,
            ) as client:
                token = await _tokens.get(client)
                response = await client.request(
                    method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
                )
                if response.status_code == 401:
                    # The cached token lapsed or was revoked — log in again and retry.
                    _tokens.clear()
                    token = await _tokens.get(client, force=True)
                    response = await client.request(
                        method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
                    )
        except httpx.HTTPError as exc:
            raise SecretStoreError(
                "Could not reach Infisical. Students' keys are unavailable until it responds."
            ) from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return response.status_code, payload

    @staticmethod
    def _explain(action: str, status: int, payload: dict) -> str:
        detail = payload.get("message") or payload.get("error") or ""
        if status in (401, 403):
            return (
                f"Infisical refused to {action} this key ({status}). The machine "
                "identity may lack access to this project or environment."
            )
        return f"Infisical could not {action} this key ({status}). {detail}".strip()
