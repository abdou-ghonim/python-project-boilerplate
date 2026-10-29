"""Mixins shared by hand-written models.

Generated models (models.py) mirror the database and get none of this; these are
for tables this application owns. The columns they add — id, created_at,
updated_at — are declared in sql/<dialect>/001_core.sql as well, because that
is what actually creates them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.extensions import db


class Base(DeclarativeBase):
    """Declarative base for the GENERATED models in models.py.

    `flask generate-models` emits `from app.models.base_model import Base`, so
    this name is part of that file's contract — renaming it breaks every
    regeneration.

    Deliberately not Flask-SQLAlchemy's db.Model: the generated classes map
    tables the database already owns, and putting them on db.metadata would hand
    `create_all()` and `drop_all()` authority over a schema this application did
    not create. Queries still go through db.session, which binds a mapper it does
    not recognise to the default engine.
    """


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Stored times are UTC everywhere in this codebase; rendering in the user's
    zone is the frontend's job. Mixing local times into a database is the kind of
    decision that is cheap now and very expensive after the first daylight-saving
    transition.
    """
    return datetime.now(timezone.utc)


class TimestampMixin:
    """created_at / updated_at maintained by the database, not the caller."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False)


class SerializerMixin:
    """`to_dict()` for API responses, with an explicit field blocklist.

    Opt-out rather than opt-in on purpose: a column added later shows up in the
    API rather than disappearing silently, and anything secret is listed in
    __private__ where a reviewer can see it.
    """

    #: Columns never serialised, whatever the caller asks for.
    __private__: tuple[str, ...] = ()

    def to_dict(self, *, exclude: tuple[str, ...] = ()) -> dict:
        # Keyed on the mapped attribute rather than the column: User maps onto
        # whatever the existing table calls its columns, and the API has to keep
        # saying "username" even when the column is "Email".
        hidden = set(self.__private__) | set(exclude)
        out = {}
        for attribute in sa_inspect(type(self)).mapper.column_attrs:
            if attribute.key in hidden:
                continue
            value = getattr(self, attribute.key)
            out[attribute.key] = value.isoformat() if isinstance(value, datetime) else value
        return out


class BaseModel(db.Model, TimestampMixin, SerializerMixin):
    """Abstract base for this application's own tables."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    def save(self) -> "BaseModel":
        db.session.add(self)
        db.session.commit()
        return self

    def delete(self) -> None:
        db.session.delete(self)
        db.session.commit()

    def __repr__(self) -> str:                                  # pragma: no cover
        return f"<{type(self).__name__} id={getattr(self, 'id', None)}>"
