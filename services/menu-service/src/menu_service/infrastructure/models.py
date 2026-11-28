from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, LargeBinary, String, Text
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

    menu_photo_version: Mapped[UUID | None]
    detail_photo_version: Mapped[UUID | None]
    menu_photo: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    detail_photo: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)

    @property
    def menu_image_url(self) -> str | None:
        if self.menu_photo_version is None:
            return None
        return f"/api/v1/menu/photos/{self.id}/menu/{self.menu_photo_version}"

    @property
    def detail_image_url(self) -> str | None:
        if self.detail_photo_version is None:
            return None
        return f"/api/v1/menu/photos/{self.id}/detail/{self.detail_photo_version}"
