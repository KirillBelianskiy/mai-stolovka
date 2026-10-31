from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    CLIENT = "CLIENT"
    COOK = "COOK"
    CASHIER = "CASHIER"
    ADMIN = "ADMIN"


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_id: int
    username: str | None
    full_name: str
