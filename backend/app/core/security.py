from datetime import timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.timeutil import utcnow

_hasher = PasswordHash.recommended()  # argon2id
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _hasher.verify(password, hashed)


def create_access_token(subject: str) -> str:
    s = get_settings()
    now = utcnow()
    payload = {"sub": subject, "iat": now, "exp": now + timedelta(minutes=s.access_token_expire_minutes)}
    return jwt.encode(payload, s.secret_key.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key.get_secret_value(), algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
