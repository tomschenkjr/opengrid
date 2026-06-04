"""
Stub authentication endpoints for OpenGrid autologin mode.
Issues signed JWTs without validating credentials.
"""

import os
import time
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from jose import jwt

router = APIRouter()

SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
ALGORITHM = "HS256"
EXPIRY_HOURS = 4


def _make_token(user_id: str = "NoAuth") -> str:
    now = int(time.time())
    payload = {
        "jti": user_id,
        "sub": user_id,
        "fname": "Public",
        "lname": "User",
        "roles": "public",
        "resources": ["all"],
        "iat": now,
        "exp": now + EXPIRY_HOURS * 3600,
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


@router.post("/users/token")
async def get_token(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    user_id = body.get("username", "NoAuth")
    token = _make_token(user_id)
    return JSONResponse(
        content={"token": token},
        headers={"X-AUTH-TOKEN": token}
    )


@router.post("/users/renew")
async def renew_token(request: Request):
    token = _make_token()
    return JSONResponse(
        content={"token": token},
        headers={"X-AUTH-TOKEN": token}
    )
