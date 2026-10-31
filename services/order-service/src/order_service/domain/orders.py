from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    PREPARING = "PREPARING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


TRANSITIONS = {
    OrderStatus.PENDING: (OrderStatus.PREPARING, frozenset({"COOK", "ADMIN"})),
    OrderStatus.PREPARING: (OrderStatus.READY, frozenset({"COOK", "ADMIN"})),
    OrderStatus.READY: (OrderStatus.COMPLETED, frozenset({"CASHIER", "ADMIN"})),
}


@dataclass(frozen=True)
class DishSnapshot:
    id: UUID
    name: str
    price: int


class OrderError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: object) -> None:
        self.status = status
        self.detail = {"code": code, "message": message, **extra}
        super().__init__(message)
