"""Demo service showing the layering: API → service → model.

The API module parses HTTP and nothing else; everything a CLI command or a
background job would also need lives here. Delete alongside the Item model once
your own domain exists.
"""
from __future__ import annotations

import logging

from app.models import Item, db
from app.redis import cache_invalidate, cached

logger = logging.getLogger(__name__)

CACHE_NAMESPACE = "items"
MAX_PAGE_SIZE = 200


class ItemService:
    @staticmethod
    def list(page: int = 1, per_page: int = 25, status: str | None = None,
             search: str | None = None) -> dict:
        """One page of items, newest first."""
        page = max(1, page)
        # Clamped rather than honoured: an unbounded per_page is a cheap way for
        # any caller to ask the database for everything.
        per_page = max(1, min(per_page, MAX_PAGE_SIZE))

        query = db.session.query(Item)
        if status:
            query = query.filter(Item.status == status)
        if search:
            # Escaped so a user searching for "100%" does not get a wildcard.
            # The escape character has to be declared, or the backslashes are
            # passed to the database as literal text and match nothing.
            term = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.filter(Item.name.ilike(f"%{term}%", escape="\\"))

        total = query.count()
        rows = (query.order_by(Item.created_at.desc())
                .limit(per_page).offset((page - 1) * per_page).all())
        return {
            "items": [row.to_dict() for row in rows],
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
        }

    @staticmethod
    @cached(CACHE_NAMESPACE, ttl=60)
    def summary() -> dict:
        """Counts by status — cached, since a dashboard asks for it constantly."""
        rows = (db.session.query(Item.status, db.func.count(Item.id))
                .group_by(Item.status).all())
        return {"by_status": {status: count for status, count in rows},
                "total": sum(count for _, count in rows)}

    @staticmethod
    def get(item_id: int) -> Item | None:
        return db.session.get(Item, item_id)

    @staticmethod
    def create(data: dict) -> Item:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("An item needs a name.")
        item = Item(
            name=name,
            description=(data.get("description") or "").strip() or None,
            status=data.get("status") or "active",
            quantity=int(data.get("quantity") or 0),
        )
        db.session.add(item)
        db.session.commit()
        # The summary is now wrong; drop it rather than wait out its TTL.
        cache_invalidate(CACHE_NAMESPACE)
        logger.info("Created item %s (%s)", item.id, item.name)
        return item

    @staticmethod
    def update(item: Item, data: dict) -> Item:
        for field in ("name", "description", "status"):
            if field in data:
                setattr(item, field, data[field])
        if "quantity" in data:
            item.quantity = int(data["quantity"])
        db.session.commit()
        cache_invalidate(CACHE_NAMESPACE)
        return item

    @staticmethod
    def delete(item: Item) -> None:
        db.session.delete(item)
        db.session.commit()
        cache_invalidate(CACHE_NAMESPACE)
