import re
import secrets

from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash(secrets.token_urlsafe(32))


def normalize_login(value: str) -> str:
    login = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", login):
        raise ValueError(
            "Staff login must contain 3–64 ASCII letters, digits, dots, underscores or hyphens"
        )
    return login


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("Staff passwords must contain 12–128 characters")
    return password_hash.hash(password)
