from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.text import normalize_name
from app.db.base import Base
from app.enums import MAX_YEAR, MIN_YEAR, TitleType

title_genres = Table(
    "title_genres",
    Base.metadata,
    Column(
        "title_id",
        Integer,
        ForeignKey("titles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "genre_id",
        Integer,
        ForeignKey("genres.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Index("ix_title_genres_genre_id", "genre_id"),
)


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    titles: Mapped[list["Title"]] = relationship(
        secondary=title_genres,
        back_populates="genres",
    )

    def __repr__(self) -> str:
        return f"<Genre id={self.id} name={self.name!r}>"


class Title(Base):
    __tablename__ = "titles"
    __table_args__ = (
        CheckConstraint(
            f"year IS NULL OR (year >= {MIN_YEAR} AND year <= {MAX_YEAR})",
            name="ck_titles_year",
        ),
        UniqueConstraint(
            "name_normalized", "year", "type", name="uq_titles_name_year_type"
        ),
        Index("ix_titles_type_year", "type", "year"),
        Index("ix_titles_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[TitleType] = mapped_column(
        SAEnum(
            TitleType,
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Приведённое имя, ловим дубли
    name_normalized: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    backdrop_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    embed_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    genres: Mapped[list[Genre]] = relationship(
        secondary=title_genres,
        back_populates="titles",
        lazy="selectin",
        order_by="Genre.name",
    )

    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="title",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(Episode.season_number, Episode.episode_number)",
    )

    @validates("name")
    def _fill_name_normalized(self, _key: str, value: str) -> str:
        self.name_normalized = normalize_name(value) if value else ""
        return value

    def __repr__(self) -> str:
        return f"<Title id={self.id} type={self.type} name={self.name!r}>"


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint(
            "title_id", "season_number", "episode_number", name="uq_episodes_position"
        ),
        CheckConstraint("season_number >= 1", name="ck_episodes_season_number"),
        CheckConstraint("episode_number >= 1", name="ck_episodes_episode_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(
        ForeignKey("titles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    season_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    embed_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    title: Mapped[Title] = relationship(back_populates="episodes")

    def __repr__(self) -> str:
        return (
            f"<Episode id={self.id} title_id={self.title_id} "
            f"s{self.season_number}e{self.episode_number}>"
        )
