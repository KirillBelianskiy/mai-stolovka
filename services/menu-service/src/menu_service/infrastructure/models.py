from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from menu_service.infrastructure.database import Base


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128))
    sort_order: Mapped[int] = mapped_column(default=0)


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (CheckConstraint("price >= 0", name="nonnegative_price"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[int]
    image_url: Mapped[str | None] = mapped_column(String(2048))
    is_available: Mapped[bool] = mapped_column(default=True)
