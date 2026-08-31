import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.auth import AuthSession, PasswordResetToken, User
from app.services.email_service import send_password_reset_email
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

password_hasher = PasswordHasher()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
        now = datetime.now(timezone.utc)
        auth_session = await self.db.scalar(
            select(AuthSession)
            .options(selectinload(AuthSession.user))
            .where(
                AuthSession.token_hash == hash_session_token(token),
                AuthSession.expires_at > now,
            )
        )
        return auth_session.user if auth_session else None

    async def logout(self, token: str | None) -> None:
        if token:
            await self.db.execute(
                delete(AuthSession).where(
                    AuthSession.token_hash == hash_session_token(token)
                )
            )
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

    async def _create_session(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        self.db.add(
            AuthSession(
                user_id=user.id,
                token_hash=hash_session_token(token),
                expires_at=datetime.now(timezone.utc)
                + timedelta(days=settings.AUTH_SESSION_DAYS),
            )
        )
        return token

    @staticmethod
    def _verify_password(password_hash: str, password: str) -> bool:
        try:
            return password_hasher.verify(password_hash, password)
        except (InvalidHashError, VerifyMismatchError):
            return False
