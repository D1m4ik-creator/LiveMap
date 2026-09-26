import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from livemap.api.errors import APIError
from livemap.core.engine import SessionDep
from livemap.db.models import AdminSession, AdminUser


ITERATIONS = 600_000
SESSION_HOURS = 8
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 1024:
        raise ValueError("Password must contain 12-1024 characters")
    salt = secrets.token_bytes(24)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        ITERATIONS,
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, count, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(count) <= 1_000_000:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.urlsafe_b64decode(salt), int(count)
        )
        return hmac.compare_digest(digest, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError, binascii.Error):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(session: SessionDep, user: AdminUser) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    session.add(AdminSession(user_id=user.id, token_hash=token_hash(token), expires_at=expires_at))
    await session.commit()
    return token, expires_at


async def current_user(
    session: SessionDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> AdminUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError("unauthorized", "Authentication required", 401)
    query = (
        select(AdminUser)
        .join(AdminSession, AdminSession.user_id == AdminUser.id)
        .where(
            AdminSession.token_hash == token_hash(credentials.credentials),
            AdminSession.expires_at > datetime.now(timezone.utc),
        )
    )
    user = (await session.execute(query)).scalar_one_or_none()
    if user is None:
        raise APIError("unauthorized", "Authentication required", 401)
    return user


def require_admin(user: AdminUser = Depends(current_user)) -> AdminUser:
    if user.role != "admin":
        raise APIError("forbidden", "Administrator role required", 403)
    return user
