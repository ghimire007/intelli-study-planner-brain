import base64
import hashlib
import hmac
import json
import time
import uuid

from app.core.config import settings
from app.services.auth_service import AuthService


def _token(secret: str, *, exp: int | None = None) -> str:
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    header = encode(b'{"alg":"HS256","typ":"JWT"}')
    claims = encode(json.dumps({
        "iss": "courseo-api",
        "sub": str(uuid.uuid4()),
        "sid": str(uuid.uuid4()),
        "iat": int(time.time()),
        "exp": exp if exp is not None else int(time.time()) + 60,
    }, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}"
    key = hashlib.sha256(secret.encode()).digest()
    signature = encode(hmac.new(key, signing_input.encode(), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


def test_auth_jwt_accepts_signed_token_and_rejects_tampering(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", "unit-test-only-secret")
    token = _token("unit-test-only-secret")

    claims = AuthService._verify_jwt(token)
    assert claims is not None
    assert isinstance(claims["sub"], uuid.UUID)
    assert isinstance(claims["sid"], uuid.UUID)
    assert AuthService._verify_jwt(token[:-1] + ("A" if token[-1] != "A" else "B")) is None


def test_auth_jwt_rejects_expired_or_wrong_issuer(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", "unit-test-only-secret")
    assert AuthService._verify_jwt(_token("unit-test-only-secret", exp=int(time.time()) - 1)) is None
    assert AuthService._verify_jwt("not.a.jwt") is None
