from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Cookie, HTTPException, status
from jose import JWTError, jwt

from app.config import get_settings


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def create_token(data: dict, hours: int = 8) -> str:
    settings = get_settings()
    payload = {**data, "exp": datetime.now(timezone.utc) + timedelta(hours=hours)}
    return jwt.encode(payload, settings.admin_secret_key, algorithm="HS256")


def verify_token(token: str) -> Optional[dict]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.admin_secret_key, algorithms=["HS256"])
    except JWTError:
        return None


def require_admin(admin_token: Optional[str] = Cookie(default=None)) -> dict:
    if not admin_token:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "login"})
    payload = verify_token(admin_token)
    if not payload or payload.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "login"})
    return payload
