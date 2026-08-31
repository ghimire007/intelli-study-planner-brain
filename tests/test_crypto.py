"""Envelope encryption: the properties the vault's safety actually rests on."""
import base64
import os
import uuid

import pytest
from app.core.crypto import (
    DecryptionError,
    MasterKeyring,
    VaultConfigurationError,
    build_aad,
    generate_master_key,
    last4,
    rewrap,
    seal,
    unseal,
)

pytestmark = pytest.mark.smoke

KEY_V1 = generate_master_key()
KEY_V2 = generate_master_key()

USER = uuid.uuid4()
CREDENTIAL = uuid.uuid4()
SECRET = "sk-ant-api03-not-a-real-key-0000000000ab12"


@pytest.fixture
def keyring() -> MasterKeyring:
    return MasterKeyring.parse(f"1:{KEY_V1}", active_version=1)


@pytest.fixture
def aad() -> bytes:
    return build_aad(USER, "anthropic", CREDENTIAL)


def test_round_trip(keyring, aad) -> None:
    sealed = seal(SECRET, aad, keyring=keyring)
    assert unseal(sealed, aad, keyring=keyring) == SECRET


def test_ciphertext_does_not_contain_the_secret(keyring, aad) -> None:
    sealed = seal(SECRET, aad, keyring=keyring)
    assert SECRET.encode() not in sealed.ciphertext
    assert SECRET.encode() not in sealed.dek_wrapped


def test_every_seal_uses_a_fresh_dek_and_nonce(keyring, aad) -> None:
    first = seal(SECRET, aad, keyring=keyring)
    second = seal(SECRET, aad, keyring=keyring)
    assert first.ciphertext != second.ciphertext
    assert first.nonce != second.nonce
    assert first.dek_wrapped != second.dek_wrapped


@pytest.mark.parametrize(
    "wrong_aad",
    [
        build_aad(uuid.uuid4(), "anthropic", CREDENTIAL),  # another user's row
        build_aad(USER, "openai", CREDENTIAL),  # relabelled provider
        build_aad(USER, "anthropic", uuid.uuid4()),  # another credential
    ],
    ids=["other-user", "other-provider", "other-credential"],
)
def test_blob_moved_to_another_row_will_not_decrypt(keyring, aad, wrong_aad) -> None:
    """The point of the AAD: copying ciphertext between rows must fail loudly."""
    sealed = seal(SECRET, aad, keyring=keyring)
    with pytest.raises(DecryptionError):
        unseal(sealed, wrong_aad, keyring=keyring)


def test_tampered_ciphertext_is_rejected(keyring, aad) -> None:
    sealed = seal(SECRET, aad, keyring=keyring)
    flipped = bytes([sealed.ciphertext[0] ^ 0x01]) + sealed.ciphertext[1:]
    with pytest.raises(DecryptionError):
        unseal(
            type(sealed)(
                ciphertext=flipped,
                nonce=sealed.nonce,
                dek_wrapped=sealed.dek_wrapped,
                dek_nonce=sealed.dek_nonce,
                key_version=sealed.key_version,
            ),
            aad,
            keyring=keyring,
        )


def test_a_different_master_key_cannot_unwrap(aad) -> None:
    sealed = seal(SECRET, aad, keyring=MasterKeyring.parse(f"1:{KEY_V1}", 1))
    impostor = MasterKeyring.parse(f"1:{generate_master_key()}", 1)
    with pytest.raises(DecryptionError):
        unseal(sealed, aad, keyring=impostor)


# ── rotation ──────────────────────────────────────────────────────────────────


def test_rewrap_moves_to_the_active_key_without_touching_the_secret(aad) -> None:
    old = MasterKeyring.parse(f"1:{KEY_V1}", active_version=1)
    both = MasterKeyring.parse(f"1:{KEY_V1},2:{KEY_V2}", active_version=2)

    sealed = seal(SECRET, aad, keyring=old)
    rotated = rewrap(sealed, keyring=both)

    assert rotated.key_version == 2
    assert rotated.dek_wrapped != sealed.dek_wrapped
    # The secret itself was never re-encrypted — that is the whole point.
    assert rotated.ciphertext == sealed.ciphertext
    assert unseal(rotated, aad, keyring=both) == SECRET


def test_both_key_versions_stay_readable_mid_rotation(aad) -> None:
    both = MasterKeyring.parse(f"1:{KEY_V1},2:{KEY_V2}", active_version=2)
    on_v1 = seal(SECRET, aad, keyring=MasterKeyring.parse(f"1:{KEY_V1}", 1))
    on_v2 = seal(SECRET, aad, keyring=both)

    assert unseal(on_v1, aad, keyring=both) == SECRET
    assert unseal(on_v2, aad, keyring=both) == SECRET


def test_rewrap_is_a_no_op_when_already_active(aad) -> None:
    keyring = MasterKeyring.parse(f"1:{KEY_V1}", 1)
    sealed = seal(SECRET, aad, keyring=keyring)
    assert rewrap(sealed, keyring=keyring) is sealed


def test_dropping_a_key_that_sealed_rows_fails_loudly(aad) -> None:
    on_v1 = seal(SECRET, aad, keyring=MasterKeyring.parse(f"1:{KEY_V1}", 1))
    only_v2 = MasterKeyring.parse(f"2:{KEY_V2}", active_version=2)
    with pytest.raises(VaultConfigurationError, match="version 1"):
        unseal(on_v1, aad, keyring=only_v2)


# ── keyring parsing ───────────────────────────────────────────────────────────


def test_bare_key_is_read_as_version_one() -> None:
    keyring = MasterKeyring.parse(KEY_V1, active_version=1)
    assert keyring.versions == [1]


def test_urlsafe_base64_is_accepted() -> None:
    raw = os.urandom(32)
    keyring = MasterKeyring.parse(base64.urlsafe_b64encode(raw).decode(), 1)
    assert keyring.key(1) == raw


@pytest.mark.parametrize(
    ("spec", "active", "match"),
    [
        ("", 1, "empty"),
        ("1:not-base64!!", 1, "base64"),
        (f"1:{base64.b64encode(os.urandom(16)).decode()}", 1, "16 bytes"),
        (f"1:{KEY_V1}", 2, "not one of the loaded versions"),
        (f"1:{KEY_V1},1:{KEY_V2}", 1, "twice"),
        (f"x:{KEY_V1}", 1, "non-numeric"),
    ],
    ids=["empty", "bad-base64", "wrong-length", "active-missing", "duplicate", "bad-version"],
)
def test_malformed_keyrings_are_rejected(spec, active, match) -> None:
    with pytest.raises(VaultConfigurationError, match=match):
        MasterKeyring.parse(spec, active)


def test_keyring_repr_does_not_leak_keys() -> None:
    keyring = MasterKeyring.parse(f"1:{KEY_V1}", 1)
    assert KEY_V1 not in repr(keyring)


def test_last4_is_all_we_ever_show() -> None:
    assert last4(SECRET) == "ab12"
    assert last4("xy") == "**xy"


# ── carrying a sealed secret through a text-only store ────────────────────────


def test_token_round_trip(keyring, aad) -> None:
    """A remote store holds one string; the same secret must survive the trip."""
    from app.core.crypto import from_token, to_token

    sealed = seal(SECRET, aad, keyring=keyring)
    token = to_token(sealed)
    assert SECRET not in token
    assert unseal(from_token(token), aad, keyring=keyring) == SECRET


def test_a_token_is_url_and_env_safe(keyring, aad) -> None:
    import re

    from app.core.crypto import to_token

    token = to_token(seal(SECRET, aad, keyring=keyring))
    assert re.fullmatch(r"[A-Za-z0-9._-]+", token)
    assert token.startswith("v1.")


@pytest.mark.parametrize(
    "text",
    ["sk-ant-api03-a-plain-key", "", "v2.1.a.b.c.d", "v1.1.a.b.c", "not-a-token"],
    ids=["plain-key", "empty", "wrong-version", "too-few-parts", "gibberish"],
)
def test_text_that_was_never_a_token_is_reported_as_such(text) -> None:
    """None, not an exception — a store may hold values written before sealing."""
    from app.core.crypto import from_token

    assert from_token(text) is None


def test_a_tampered_token_will_not_open(keyring, aad) -> None:
    from app.core.crypto import from_token, to_token

    parts = to_token(seal(SECRET, aad, keyring=keyring)).split(".")
    parts[3] = parts[3][:-4] + ("AAAA" if not parts[3].endswith("AAAA") else "BBBB")
    with pytest.raises(DecryptionError):
        unseal(from_token(".".join(parts)), aad, keyring=keyring)


def test_a_token_moved_to_another_credential_will_not_open(keyring, aad) -> None:
    """The AAD binds it to one row, inside a remote store just as in our table."""
    from app.core.crypto import from_token, to_token

    token = to_token(seal(SECRET, aad, keyring=keyring))
    elsewhere = build_aad(USER, "anthropic", uuid.uuid4())
    with pytest.raises(DecryptionError):
        unseal(from_token(token), elsewhere, keyring=keyring)
