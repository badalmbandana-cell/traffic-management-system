"""
JWT issuing/verification for the API.

Stateless auth: the token itself carries username + role, signed with a
secret key - the server doesn't need to hit the DB on every request to
check who's making it (only at login time, to verify the password).

SECRET KEY: reads from the TMS_JWT_SECRET environment variable. If unset,
falls back to a fixed dev-only secret AND prints a loud warning - a real
deployment must set a real secret (e.g. `openssl rand -hex 32`), or anyone
who reads this source code could forge valid tokens.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, TypedDict

import jwt  # PyJWT

_DEV_ONLY_SECRET = "dev-only-insecure-secret-CHANGE-ME-via-TMS_JWT_SECRET"
SECRET_KEY = os.environ.get("TMS_JWT_SECRET")
if not SECRET_KEY:
    SECRET_KEY = _DEV_ONLY_SECRET
    print(
        "[auth] WARNING: TMS_JWT_SECRET is not set - using an insecure default "
        "signing key. Set a real secret before deploying: "
        "export TMS_JWT_SECRET=$(openssl rand -hex 32)"
    )

ALGORITHM = "HS256"
DEFAULT_EXPIRE_MINUTES = 8 * 60  # 8-hour shift-length token


class TokenPayload(TypedDict):
    sub: str   # username
    role: str
    exp: int


def create_access_token(username: str, role: str, expires_minutes: int = DEFAULT_EXPIRE_MINUTES) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> TokenPayload:
    """Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError on failure."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])  # type: ignore[return-value]
