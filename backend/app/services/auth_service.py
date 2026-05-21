import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.core.database import (
    create_user as db_create_user,
    create_user_session,
    delete_user_session,
    get_user_by_email,
    get_user_by_session_hash,
)
from app.core.models import User

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000
SESSION_DAYS = 30


def create_user(email: str, password: str, display_name: str | None = None) -> User:
    normalized_email = _normalize_email(email)
    clean_display_name = _normalize_display_name(display_name)
    _validate_email(normalized_email)
    _validate_password(password)

    if get_user_by_email(normalized_email) is not None:
        raise ValueError("email_already_registered")

    return db_create_user(
        email=normalized_email,
        password_hash=hash_password(password),
        display_name=clean_display_name,
    )


def authenticate_user(email: str, password: str) -> User | None:
    normalized_email = _normalize_email(email)
    row = get_user_by_email(normalized_email)
    if row is None:
        return None

    if not verify_password(password, row["password_hash"]):
        return None

    return User(
        user_id=row["user_id"],
        email=row["email"],
        display_name=row["display_name"],
        avatar_initial=row["avatar_initial"],
        plan=row["plan"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(
        timespec="seconds"
    )
    create_user_session(
        user_id=user_id,
        token_hash=hash_session_token(token),
        expires_at=expires_at,
    )
    return token


def get_user_by_session_token(token: str) -> User | None:
    return get_user_by_session_hash(hash_session_token(token))


def delete_session(token: str) -> None:
    delete_user_session(hash_session_token(token))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return (
        f"{PASSWORD_HASH_ALGORITHM}"
        f"${PASSWORD_HASH_ITERATIONS}"
        f"${salt.hex()}"
        f"${password_hash.hex()}"
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hash_hex = password_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != PASSWORD_HASH_ALGORITHM:
        return False

    actual_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations),
    )
    return hmac.compare_digest(actual_hash.hex(), expected_hash_hex)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_display_name(display_name: str | None) -> str | None:
    if display_name is None:
        return None
    stripped = display_name.strip()
    return stripped or None


def _validate_email(email: str) -> None:
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise ValueError("invalid_email")


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("password_too_short")
