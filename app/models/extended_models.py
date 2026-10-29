"""Hand-written models.

Kept apart from models.py because that file is regenerated in full from the
database; anything written there is lost on the next `flask generate-models`.
A table only needs a class here when it carries behaviour or when you want it
to exist before you have a database to reflect — otherwise reflect it.

The account model is not here: it lives in user.py, because which table and
which columns it maps are configuration rather than source.
"""
from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import BaseModel


class Item(BaseModel):
    """Demo model behind /api/items.

    Here so the boilerplate ships a working vertical slice — model, service, API,
    CLI seed and a frontend page. Delete it, and the `item` table in each
    sql/*/001_core.sql, once your own domain arrives.
    """

    __tablename__ = "item"
    __table_args__ = (Index("ix_item_status_created", "status", "created_at"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False,
                                        index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
