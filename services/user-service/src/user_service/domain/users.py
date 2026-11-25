from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    CLIENT = "CLIENT"
    COOK = "COOK"
    CASHIER = "CASHIER"
    ADMIN = "ADMIN"


class RecipientPermissionState(StrEnum):
    UNKNOWN = "unknown"
    ALLOWED = "allowed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_id: int
    username: str | None
    full_name: str
    auth_date: int
    allows_write_to_pm: bool | None
