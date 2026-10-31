import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl

from user_service.domain.users import TelegramIdentity


class InvalidInitData(ValueError):
    pass


def validate_init_data(
    raw: str,
    bot_token: str,
    *,
    max_age: int = 300,
    future_skew: int = 30,
    now: int | None = None,
) -> TelegramIdentity:
    """Validate the original Telegram query string before trusting any user fields."""
    try:
        if not raw or len(raw) > 16384 or re.search(r"%(?![0-9a-fA-F]{2})", raw):
            raise InvalidInitData()
        pairs = parse_qsl(
            raw,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=64,
        )
        fields = dict(pairs)
        if len(fields) != len(pairs) or not all(key for key, _ in pairs):
            raise InvalidInitData()
        signature = fields.pop("hash", "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
            raise InvalidInitData()
        data = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.lower()):
            raise InvalidInitData()
        auth_date_text = fields["auth_date"]
        if not auth_date_text.isascii() or not auth_date_text.isdecimal():
            raise InvalidInitData()
        auth_date = int(auth_date_text)
        current = int(time.time()) if now is None else now
        if current - auth_date > max_age or auth_date - current > future_skew:
            raise InvalidInitData()
        user = json.loads(fields["user"])
        if not isinstance(user, dict):
            raise InvalidInitData()
        telegram_id = user.get("id")
        if type(telegram_id) is not int or not 0 < telegram_id <= 2**63 - 1:
            raise InvalidInitData()
        first = user.get("first_name")
        last = user.get("last_name", "")
        username = user.get("username")
        if not isinstance(first, str) or not first.strip() or not isinstance(last, str):
            raise InvalidInitData()
        if username is not None and (not isinstance(username, str) or len(username) > 64):
            raise InvalidInitData()
        full_name = " ".join(part.strip() for part in (first, last) if part.strip())
        if len(full_name) > 256:
            raise InvalidInitData()
        return TelegramIdentity(telegram_id, username, full_name)
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise InvalidInitData("Invalid Telegram authentication data") from error
