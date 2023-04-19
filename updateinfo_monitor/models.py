from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    arch: Mapped[str] = mapped_column(String(10))
    debuginfo: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(Text)
    repomd_etag: Mapped[str] = mapped_column(Text, nullable=True)
    repomd_checksum: Mapped[str] = mapped_column(Text, nullable=True)
    check_ts: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)
    check_result: Mapped[dict] = mapped_column(JSONB, nullable=True)
    updateinfo: Mapped[list["UpdateRecord"]] = relationship(
        back_populates="repository",
    )

    @property
    def full_name(self) -> str:
        return f"{self.name}.{self.arch}"


class UpdateRecord(Base):
    __tablename__ = "update_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[str] = mapped_column(Text)
    updated_date: Mapped[datetime] = mapped_column(DateTime)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    repository: Mapped["Repository"] = relationship(
        back_populates="updateinfo",
    )
