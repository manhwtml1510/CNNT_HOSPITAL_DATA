
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import settings


password_hasher = PasswordHash.recommended()

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    #Băm mật khẩu bằng thuật toán
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    #so sánh mật khẩu người dùng với chuỗi băm đã lưu
    return password_hasher.verify(password, password_hash)


def create_access_token(user_id: int) -> str:
    #tạo jwt có time ngắn
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(
        minutes=settings.access_token_expire_minutes
    )

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expires_at,
        "type": "access",
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    #xác minh chữ ký
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "iat", "exp", "type"]},
    )

    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Invalid token type")

    return payload
