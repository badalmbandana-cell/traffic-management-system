"""
FastAPI auth dependencies - plug these into any endpoint with `Depends(...)`.

require_role("admin") -> only admins may call this endpoint
require_role("admin", "operator") -> either role may call it
get_current_user (no role filter) -> any logged-in user (all 3 roles)

Uses FastAPI's OAuth2PasswordBearer, which is what makes the "Authorize"
button in the auto-generated /docs page work out of the box.
"""
from __future__ import annotations

from typing import TypedDict

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from auth.jwt_utils import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class CurrentUser(TypedDict):
    username: str
    role: str


def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired, please log in again",
                             headers={"WWW-Authenticate": "Bearer"})
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token",
                             headers={"WWW-Authenticate": "Bearer"})
    return {"username": payload["sub"], "role": payload["role"]}


def require_role(*allowed_roles: str):
    """Dependency factory: require_role('admin') or require_role('admin', 'operator')."""

    def _checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current["role"] not in allowed_roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{current['role']}' is not permitted to perform this action "
                f"(requires: {', '.join(allowed_roles)})",
            )
        return current

    return _checker
