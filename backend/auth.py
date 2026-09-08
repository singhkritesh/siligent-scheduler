from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, Request, Response, status

from .config import settings
from .db import append_audit, connect, transaction

SESSION_COOKIE = "siligent_session"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
    )


def create_password(password: str) -> tuple[bytes, bytes]:
    salt = secrets.token_bytes(16)
    return salt, hash_password(password, salt)


def verify_password(password: str, salt: bytes, expected: bytes) -> bool:
    return hmac.compare_digest(hash_password(password, salt), expected)


def session_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def authenticate(username: str, password: str, response: Response) -> dict:
    correlation_id = str(uuid.uuid4())
    with transaction() as connection:
        credential = connection.execute(
            """
            SELECT u.id, u.display_name, u.role::text AS role, u.active,
                   c.password_salt, c.password_hash, c.failed_attempts,
                   c.locked_until
              FROM local_credentials c
              JOIN app_users u ON u.id = c.user_id
             WHERE lower(c.username) = lower(%s)
             FOR UPDATE
            """,
            (username.strip(),),
        ).fetchone()

        now = datetime.now(UTC)
        valid = bool(
            credential
            and credential["active"]
            and (
                credential["locked_until"] is None
                or credential["locked_until"] <= now
            )
            and verify_password(
                password,
                bytes(credential["password_salt"]),
                bytes(credential["password_hash"]),
            )
        )
        if not valid:
            if credential:
                attempts = credential["failed_attempts"] + 1
                locked_until = now + timedelta(minutes=15) if attempts >= 5 else None
                connection.execute(
                    """
                    UPDATE local_credentials
                       SET failed_attempts = %s, locked_until = %s
                     WHERE user_id = %s
                    """,
                    (attempts, locked_until, credential["id"]),
                )
            append_audit(
                connection,
                actor_id=str(credential["id"]) if credential else None,
                event_type="authentication.login",
                entity_type="user",
                entity_id=str(credential["id"]) if credential else None,
                correlation_id=correlation_id,
                outcome="denied",
                details={"reason": "invalid_credentials"},
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        connection.execute(
            "UPDATE local_credentials SET failed_attempts = 0, locked_until = NULL WHERE user_id = %s",
            (credential["id"],),
        )
        raw_token = secrets.token_urlsafe(48)
        expires = now + timedelta(hours=settings.session_hours)
        connection.execute(
            "INSERT INTO user_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
            (session_hash(raw_token), credential["id"], expires),
        )
        append_audit(
            connection,
            actor_id=str(credential["id"]),
            event_type="authentication.login",
            entity_type="user",
            entity_id=str(credential["id"]),
            correlation_id=correlation_id,
        )

    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return {
        "id": str(credential["id"]),
        "display_name": credential["display_name"],
        "role": credential["role"],
    }


def current_user(
    request: Request,
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    with connect() as connection:
        user = connection.execute(
            """
            SELECT u.id, u.display_name, u.role::text AS role
              FROM user_sessions s
              JOIN app_users u ON u.id = s.user_id
             WHERE s.token_hash = %s
               AND s.revoked_at IS NULL
               AND s.expires_at > transaction_timestamp()
               AND u.active
            """,
            (session_hash(token),),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
        connection.execute(
            "UPDATE user_sessions SET last_seen_at = transaction_timestamp() WHERE token_hash = %s",
            (session_hash(token),),
        )
        connection.commit()
    return {"id": str(user["id"]), "display_name": user["display_name"], "role": user["role"]}


def require_roles(*roles: str):
    def dependency(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
        return user

    return dependency


def logout(token: str | None, response: Response, user: dict) -> None:
    if token:
        correlation_id = str(uuid.uuid4())
        with transaction() as connection:
            connection.execute(
                "UPDATE user_sessions SET revoked_at = transaction_timestamp() WHERE token_hash = %s",
                (session_hash(token),),
            )
            append_audit(
                connection,
                actor_id=user["id"],
                event_type="authentication.logout",
                entity_type="user",
                entity_id=user["id"],
                correlation_id=correlation_id,
            )
    response.delete_cookie(SESSION_COOKIE, path="/")
