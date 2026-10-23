"""JWT (HS256) и хеши паролей на стандартной библиотеке - без внешних зависимостей."""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid

from app.core.config import get_settings

PBKDF2_ITERATIONS = 600_000


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(message: str) -> str:
    key = get_settings().jwt_secret.encode()
    return _b64encode(hmac.new(key, message.encode(), hashlib.sha256).digest())


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    """Возвращает токен и время жизни в секундах."""
    ttl = get_settings().access_token_ttl_minutes * 60
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64encode(json.dumps({"sub": str(user_id), "exp": int(time.time()) + ttl}).encode())
    return f"{header}.{payload}.{_sign(f'{header}.{payload}')}", ttl


def decode_access_token(token: str) -> uuid.UUID:
    try:
        header, payload, signature = token.split(".")
    except ValueError as e:
        raise InvalidTokenError from e
    if not hmac.compare_digest(signature, _sign(f"{header}.{payload}")):
        raise InvalidTokenError
    try:
        claims = json.loads(_b64decode(payload))
        user_id = uuid.UUID(claims["sub"])
        expires_at = int(claims["exp"])
    except (ValueError, KeyError, TypeError) as e:
        raise InvalidTokenError from e
    if expires_at < time.time():
        raise InvalidTokenError
    return user_id
