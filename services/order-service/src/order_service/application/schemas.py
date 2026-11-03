from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field, model_validator

from order_service.domain.orders import OrderStatus

MAX_INTEGER = 2**31 - 1


class SlotWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: AwareDatetime
    end_time: AwareDatetime
    capacity: int = Field(strict=True, gt=0, le=MAX_INTEGER)

    @model_validator(mode="after")
    def time_order(self) -> Self:
        if self.start_time >= self.end_time:
            raise ValueError("Slot start must precede its end")
        return self


class SlotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    start_time: datetime
    end_time: datetime
    capacity: int
    current_orders: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def remaining_capacity(self) -> int:
        return self.capacity - self.current_orders


class CartLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    menu_item_id: UUID
    quantity: int = Field(strict=True, gt=0, le=MAX_INTEGER)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot_id: UUID
    items: list[CartLine] = Field(min_length=1, max_length=100)
    expected_total_amount: int = Field(strict=True, ge=0, le=MAX_INTEGER)

    @model_validator(mode="after")
    def unique_lines(self) -> Self:
        if len({item.menu_item_id for item in self.items}) != len(self.items):
            raise ValueError("Each dish must appear once; use quantity instead of duplicate lines")
        self.items.sort(key=lambda item: str(item.menu_item_id))
        return self


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    menu_item_id: UUID
    quantity: int
    price_at_moment: int
    name_at_moment: str


class OrderRead(BaseModel):
    id: UUID
    order_number: str
    user_id: UUID
    slot_id: UUID
    slot_start_time: datetime
    slot_end_time: datetime
    status: OrderStatus
    total_amount: int
    payment_status: Literal["NOT_REQUIRED", "DEMO_PAID", "DEMO_REFUNDED"] = "NOT_REQUIRED"
    version: int
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]


class OrderPage(BaseModel):
    items: list[OrderRead]
    total: int
    limit: int
    offset: int


class VersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(strict=True, ge=1, le=MAX_INTEGER)


class StatusChange(VersionInput):
    status: OrderStatus


class DemoCreditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    amount: int = Field(strict=True, gt=0, le=MAX_INTEGER)


class WalletRead(BaseModel):
    user_id: UUID
    balance: int
    currency: Literal["RUB"] = "RUB"
    demo: Literal[True] = True
    checkout_payment_enabled: bool


class DemoCreditRead(BaseModel):
    id: UUID
    user_id: UUID
    amount: int
    balance_after: int
    demo: Literal[True] = True
