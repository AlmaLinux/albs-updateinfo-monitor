from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


OldRepositories = Table(
    "old_repositories_mapping",
    Base.metadata,
    Column(
        "repository_id",
        ForeignKey(
            "repositories.id",
            name="old_repositories_mapping_repository_id_fkey",
        ),
        primary_key=True,
    ),
    Column(
        "old_repository_id",
        ForeignKey(
            "repositories.id",
            name="old_repositories_mapping_old_repository_id_fkey",
        ),
        primary_key=True,
    ),
)


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
    check_result_checksum: Mapped[str] = mapped_column(Text, nullable=True)
    is_old: Mapped[bool] = mapped_column(Boolean, default=False)
    updateinfo: Mapped[list["UpdateRecord"]] = relationship(
        back_populates="repository",
    )
    old_repositories: Mapped[list["Repository"]] = relationship(
        "Repository",
        secondary=OldRepositories,
        primaryjoin=(OldRepositories.c.repository_id == id),
        secondaryjoin=(OldRepositories.c.old_repository_id == id),
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
