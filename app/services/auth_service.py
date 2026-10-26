import hashlib
import base64
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.core.checkpointer import delete_checkpoint_threads
from app.core.config import settings
from app.core.crypto import get_keyring
from app.models.auth import AuthSession, PasswordResetToken, User
from app.models.session import ChatSession
from app.services.email_service import send_password_reset_email
from app.services.vault_service import VaultService
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

password_hasher = PasswordHasher()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt_signing_key() -> bytes:
    configured = settings.AUTH_JWT_SECRET
    if configured:
        return hashlib.sha256(configured.encode()).digest()
    # The oldest key remains configured while encrypted user keys depend on it;
    # using it keeps session verification stable across active-key rotation.
    keyring = get_keyring()
    return hmac.new(keyring.key(min(keyring.versions)), b"courseo:auth-jwt:v1", hashlib.sha256).digest()


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(
        self, email: str, password: str, display_name: str | None
    ) -> tuple[User, str]:
        existing = await self.db.scalar(select(User.id).where(User.email == email))
        if existing:
            raise ValueError("An account with this email already exists")

        user = User(
            email=email,
            display_name=display_name,
            password_hash=password_hasher.hash(password),
        )
        self.db.add(user)
        await self.db.flush()
        token = await self._create_session(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user, token

    async def login(self, email: str, password: str) -> tuple[User, str]:
        user = await self.db.scalar(select(User).where(User.email == email))
        if user is None or not self._verify_password(user.password_hash if user else "", password):
            raise ValueError("Invalid email or password")

        if password_hasher.check_needs_rehash(user.password_hash):
            user.password_hash = password_hasher.hash(password)
        token = await self._create_session(user)
        await self.db.commit()
        return user, token

    async def authenticate(self, token: str | None) -> User | None:
        if not token:
            return None
        claims = self._verify_jwt(token)
        if claims is None:
            return None
        now = datetime.now(timezone.utc)
        auth_session = await self.db.scalar(
            select(AuthSession)
            .options(selectinload(AuthSession.user))
            .where(
                AuthSession.token_hash == hash_session_token(token),
                AuthSession.id == claims["sid"],
                AuthSession.user_id == claims["sub"],
                AuthSession.expires_at > now,
            )
        )
        return auth_session.user if auth_session else None

    async def logout(self, token: str | None) -> None:
        if token:
            session = await self.db.scalar(
                select(AuthSession).options(selectinload(AuthSession.user)).where(
                    AuthSession.token_hash == hash_session_token(token)
                )
            )
            if session:
                user = session.user
                await self.db.delete(session)
                if user.is_guest:
                    await self._purge_user_data(user)
            await self.db.commit()

    async def create_guest(self) -> tuple[User, str]:
        guest_id = uuid.uuid4()
        user = User(
            id=guest_id,
            email=f"guest-{guest_id.hex}@guest.courseo.invalid",
            display_name="Guest",
            password_hash=password_hasher.hash(secrets.token_urlsafe(48)),
            is_guest=True,
        )
        self.db.add(user)
        await self.db.flush()
        token = await self._create_session(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user, token

    async def delete_guest(self, user: User) -> None:
        if not user.is_guest:
            raise ValueError("This endpoint is only available for guest workspaces")
        await self._purge_user_data(user)
        await self.db.commit()

    async def request_password_reset(self, email: str) -> None:
        user = await self.db.scalar(select(User).where(User.email == email))
        if user is None:
            return

        now = datetime.now(timezone.utc)
        await self.db.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        )

        raw_token = secrets.token_urlsafe(32)
        self.db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_session_token(raw_token),
                expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
            )
        )
        await self.db.commit()
        send_password_reset_email(to_email=user.email, raw_token=raw_token)

    async def reset_password(self, token: str, new_password: str) -> None:
        now = datetime.now(timezone.utc)
        reset_token = await self.db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == hash_session_token(token),
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
        )
        if reset_token is None:
            raise ValueError("Invalid or expired reset link")

        user = await self.db.get(User, reset_token.user_id)
        if user is None:
            raise ValueError("Invalid or expired reset link")

        user.password_hash = password_hasher.hash(new_password)
        reset_token.used_at = now
        await self.db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        await self.db.commit()

    async def delete_account(self, user: User, password: str) -> None:
        if not self._verify_password(user.password_hash, password):
            raise ValueError("Invalid password")

        await self._purge_user_data(user)
        await self.db.commit()

    async def _purge_user_data(self, user: User) -> None:
        session_ids = (
            await self.db.scalars(
                select(ChatSession.id).where(ChatSession.user_id == user.id)
            )
        ).all()
        await delete_checkpoint_threads(session_ids)
        await VaultService(self.db).purge_keys_for_user(user)
        await self.db.delete(user)

    async def _create_session(self, user: User) -> str:
        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=settings.AUTH_SESSION_DAYS)
        header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        payload = _b64url(json.dumps({
            "iss": "courseo-api", "sub": str(user.id), "sid": str(session_id),
            "iat": int(now.timestamp()), "exp": int(expires_at.timestamp()),
        }, separators=(",", ":")).encode())
        signing_input = f"{header}.{payload}"
        token = f"{signing_input}.{_b64url(hmac.new(_jwt_signing_key(), signing_input.encode(), hashlib.sha256).digest())}"
        self.db.add(
            AuthSession(
                id=session_id,
                user_id=user.id,
                token_hash=hash_session_token(token),
                expires_at=expires_at,
            )
        )
        return token

    @staticmethod
    def _verify_jwt(token: str) -> dict | None:
        try:
            header_b64, payload_b64, signature_b64 = token.split(".")
            signing_input = f"{header_b64}.{payload_b64}"
            expected = hmac.new(_jwt_signing_key(), signing_input.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, base64.urlsafe_b64decode(signature_b64 + "=" * (-len(signature_b64) % 4))):
                return None
            header = json.loads(base64.urlsafe_b64decode(header_b64 + "=" * (-len(header_b64) % 4)))
            claims = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
            if header != {"alg": "HS256", "typ": "JWT"} or claims.get("iss") != "courseo-api":
                return None
            if int(claims["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
                return None
            claims["sid"] = uuid.UUID(claims["sid"])
            claims["sub"] = uuid.UUID(claims["sub"])
            return claims
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    @staticmethod
    def _verify_password(password_hash: str, password: str) -> bool:
        try:
            return password_hasher.verify(password_hash, password)
        except (InvalidHashError, VerifyMismatchError):
            return False
