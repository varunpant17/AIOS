from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
    )

    city: Mapped[str] = mapped_column(
        String(100),
    )