import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.auth import AuthSession, User
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
