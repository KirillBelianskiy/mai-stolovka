from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class CategoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=128)
    sort_order: int = Field(default=0, strict=True, ge=-(2**31), le=2**31 - 1)


class CategoryRead(CategoryWrite):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class ItemWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    category_id: UUID
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=10000)
    price: int = Field(strict=True, ge=0, le=2**31 - 1)
    image_url: str | None = Field(default=None, max_length=2048)
    is_available: bool = Field(default=True, strict=True)

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(HttpUrl(value))


class ItemRead(ItemWrite):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class ItemPage(BaseModel):
    items: list[ItemRead]
    total: int
    limit: int
    offset: int


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("item_ids")
    @classmethod
    def unique_items(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Dish IDs must be unique")
        return value


class SnapshotResponse(BaseModel):
    items: list[ItemRead]
