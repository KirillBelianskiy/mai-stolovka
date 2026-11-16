from dataclasses import dataclass
from datetime import timedelta
from random import uniform
from typing import Literal
from uuid import UUID

MAX_ATTEMPTS = 8
READY_WINDOW = timedelta(hours=24)
CLAIM_LEASE = timedelta(seconds=60)
NETWORK_TIMEOUT = 10


def retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=uniform(1, min(300, 2 ** min(attempt, 9))))


@dataclass(frozen=True)
class Claim:
    order_id: UUID
    version: int
    token: UUID
    user_id: UUID
    order_number: str


@dataclass(frozen=True, repr=False)
class Recipient:
    state: str
    revision: int = 0
    chat_id: int | None = None


@dataclass(frozen=True)
class DeliveryResult:
    outcome: Literal[
        "sent", "uncertain", "retry", "rate_limited", "blocked", "bad_request", "paused"
    ]
    message_id: int | None = None
    retry_after: int | None = None


@dataclass(frozen=True, repr=False)
class BlockReport:
    user_id: UUID
    notification_id: UUID
    revision: int
    chat_id: int | None
    state: str
    tries: int


ReportResult = Literal["reported", "retry", "revision_conflict", "stale", "rejected"]
