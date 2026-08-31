"""Envelope encryption for user-supplied secrets (their own LLM API keys).

Two layers, the way Infisical does it:

    SECRETS_MASTER_KEYS (KEK, env)  --AES-256-GCM-->  DEK (32 bytes, per credential)
    DEK                             --AES-256-GCM-->  the API key

Only the wrapped DEK and the ciphertext are ever stored. That buys two things a
single-layer scheme does not:

* **Rotation is cheap.** Changing the master key re-wraps N tiny data keys in one
  transaction instead of decrypting and re-encrypting every secret, and
  ``key_version`` lets the old and new master keys coexist while it runs.
* **Ciphertext is bound to its row.** The API key is authenticated against
  ``build_aad(...)`` — the user, provider and credential id it belongs to — so a
  blob copied into somebody else's row fails to decrypt rather than quietly
  succeeding.

Losing every master key is unrecoverable by design; students simply re-enter
their keys. Keep the key in the deploy environment, never in git.
"""
from __future__ import annotations

import base64
import binascii
import os
import uuid
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import settings
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASTER_KEY_BYTES = 32
DEK_BYTES = 32
NONCE_BYTES = 12

# Domain separator for the DEK-wrapping layer. Constant (not row-derived) so that
# a DEK can be re-wrapped under a new master key without the row's identity.
_DEK_AAD = b"intellistudy:llm-credential-dek:v1"


class VaultConfigurationError(RuntimeError):
    """The master keyring is missing or malformed — the vault cannot be used."""


class DecryptionError(RuntimeError):
    """Ciphertext failed authentication: wrong key, wrong AAD, or tampered bytes."""


@dataclass(frozen=True)
class SealedSecret:
    """Exactly what gets persisted for one secret. Holds no readable key."""

    ciphertext: bytes
    nonce: bytes
    dek_wrapped: bytes
    dek_nonce: bytes
    key_version: int


@dataclass(frozen=True)
class MasterKeyring:
    """The master keys currently loadable, and which one new secrets are wrapped with."""

    keys: dict[int, bytes] = field(repr=False)
    active_version: int

    @classmethod
    def parse(cls, spec: str, active_version: int) -> MasterKeyring:
        """Read ``"1:<b64>,2:<b64>"``. A bare base64 key is read as version 1."""
        keys: dict[int, bytes] = {}
        for entry in (e.strip() for e in spec.split(",")):
            if not entry:
                continue
            version_text, _, key_text = entry.rpartition(":")
            try:
                version = int(version_text) if version_text else 1
            except ValueError as exc:
                raise VaultConfigurationError(
                    f"SECRETS_MASTER_KEYS entry {entry[:12]!r}… has a non-numeric version"
                ) from exc
            if version in keys:
                raise VaultConfigurationError(f"SECRETS_MASTER_KEYS lists version {version} twice")
            keys[version] = _decode_master_key(key_text, version)

        if not keys:
            raise VaultConfigurationError(
                "SECRETS_MASTER_KEYS is empty — generate one with "
                '`python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"`'
            )
        if active_version not in keys:
            raise VaultConfigurationError(
                f"SECRETS_ACTIVE_KEY_VERSION={active_version} is not one of the "
                f"loaded versions {sorted(keys)}"
            )
        return cls(keys=keys, active_version=active_version)

    def key(self, version: int) -> bytes:
        try:
            return self.keys[version]
        except KeyError as exc:
            raise VaultConfigurationError(
                f"No master key loaded for version {version} — it encrypted existing "
                f"rows, so it must stay in SECRETS_MASTER_KEYS (loaded: {sorted(self.keys)})"
            ) from exc

    @property
    def versions(self) -> list[int]:
        return sorted(self.keys)


def _decode_master_key(text: str, version: int) -> bytes:
    raw = text.strip()
    # Accept both alphabets: `openssl rand -base64 32` emits the standard one,
    # `secrets.token_urlsafe` the URL-safe one. (base64.urlsafe_b64decode takes no
    # `validate` kwarg, hence altchars on b64decode rather than the other helper.)
    for altchars in (None, b"-_"):
        try:
            key = base64.b64decode(raw, altchars=altchars, validate=True)
        except Exception:
            continue
        if len(key) == MASTER_KEY_BYTES:
            return key
        raise VaultConfigurationError(
            f"Master key version {version} decodes to {len(key)} bytes, expected {MASTER_KEY_BYTES}"
        )
    raise VaultConfigurationError(f"Master key version {version} is not valid base64")


@lru_cache
def get_keyring() -> MasterKeyring:
    """The process-wide keyring. Raises VaultConfigurationError if unconfigured."""
    return MasterKeyring.parse(
        settings.SECRETS_MASTER_KEYS, settings.SECRETS_ACTIVE_KEY_VERSION
    )


def vault_is_configured() -> bool:
    """True when secrets can actually be sealed — used by /health and startup logging."""
    try:
        get_keyring()
    except VaultConfigurationError:
        return False
    return True


def generate_master_key() -> str:
    """A fresh base64 master key, ready to paste into SECRETS_MASTER_KEYS."""
    return base64.b64encode(os.urandom(MASTER_KEY_BYTES)).decode()


def build_aad(user_id: uuid.UUID, provider: str, credential_id: uuid.UUID) -> bytes:
    """Bind a ciphertext to the row it belongs to.

    Decryption of a blob moved to another user, provider or credential fails
    instead of succeeding, so a stray UPDATE or an injection can't reassign keys.
    """
    return f"llm-credential|{user_id}|{provider}|{credential_id}".encode()


def seal(plaintext: str, aad: bytes, *, keyring: MasterKeyring | None = None) -> SealedSecret:
    keyring = keyring or get_keyring()
    dek = os.urandom(DEK_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode(), aad)

    dek_nonce = os.urandom(NONCE_BYTES)
    master = keyring.key(keyring.active_version)
    dek_wrapped = AESGCM(master).encrypt(dek_nonce, dek, _DEK_AAD)

    return SealedSecret(
        ciphertext=ciphertext,
        nonce=nonce,
        dek_wrapped=dek_wrapped,
        dek_nonce=dek_nonce,
        key_version=keyring.active_version,
    )


def unseal(sealed: SealedSecret, aad: bytes, *, keyring: MasterKeyring | None = None) -> str:
    keyring = keyring or get_keyring()
    dek = _unwrap_dek(sealed, keyring)
    try:
        return AESGCM(dek).decrypt(sealed.nonce, sealed.ciphertext, aad).decode()
    except InvalidTag as exc:
        raise DecryptionError(
            "Secret failed authentication — the row's identity does not match the "
            "ciphertext, or the stored bytes were altered"
        ) from exc


def rewrap(sealed: SealedSecret, *, keyring: MasterKeyring | None = None) -> SealedSecret:
    """Re-wrap the DEK under the active master key. The secret itself is untouched.

    This is the whole point of the two layers: rotating the master key never has
    to see, or re-encrypt, a single API key.
    """
    keyring = keyring or get_keyring()
    if sealed.key_version == keyring.active_version:
        return sealed

    dek = _unwrap_dek(sealed, keyring)
    dek_nonce = os.urandom(NONCE_BYTES)
    master = keyring.key(keyring.active_version)
    return SealedSecret(
        ciphertext=sealed.ciphertext,
        nonce=sealed.nonce,
        dek_wrapped=AESGCM(master).encrypt(dek_nonce, dek, _DEK_AAD),
        dek_nonce=dek_nonce,
        key_version=keyring.active_version,
    )


def _unwrap_dek(sealed: SealedSecret, keyring: MasterKeyring) -> bytes:
    master = keyring.key(sealed.key_version)
    try:
        return AESGCM(master).decrypt(sealed.dek_nonce, sealed.dek_wrapped, _DEK_AAD)
    except InvalidTag as exc:
        raise DecryptionError(
            f"Could not unwrap the data key with master key version {sealed.key_version} — "
            "the configured key is not the one that sealed this row"
        ) from exc


# ── carrying a sealed secret somewhere that only stores text ────────────────
#
# Postgres takes the four byte columns directly. A remote store like Infisical
# holds a single string, so the same SealedSecret is flattened into one token:
#
#     v1.<key_version>.<nonce>.<ciphertext>.<dek_nonce>.<dek_wrapped>
#
# base64url without padding, so the token survives anywhere a secret value can go.

SEALED_TOKEN_VERSION = "v1"
_SEALED_TOKEN_PARTS = 6


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def to_token(sealed: SealedSecret) -> str:
    """Flatten a sealed secret into one string, for stores that only hold text."""
    return ".".join(
        (
            SEALED_TOKEN_VERSION,
            str(sealed.key_version),
            _b64(sealed.nonce),
            _b64(sealed.ciphertext),
            _b64(sealed.dek_nonce),
            _b64(sealed.dek_wrapped),
        )
    )


def from_token(token: str) -> SealedSecret | None:
    """Parse a token back, or None if this text was never one of ours.

    Returning None rather than raising is what lets a store hold a mix of sealed
    tokens and values written before sealing was introduced.
    """
    parts = token.split(".")
    if len(parts) != _SEALED_TOKEN_PARTS or parts[0] != SEALED_TOKEN_VERSION:
        return None
    try:
        return SealedSecret(
            key_version=int(parts[1]),
            nonce=_unb64(parts[2]),
            ciphertext=_unb64(parts[3]),
            dek_nonce=_unb64(parts[4]),
            dek_wrapped=_unb64(parts[5]),
        )
    except (ValueError, binascii.Error):
        return None


def last4(secret: str) -> str:
    """The only part of a key we ever show back to the student."""
    tail = secret.strip()[-4:]
    return tail if len(tail) == 4 else tail.rjust(4, "*")
