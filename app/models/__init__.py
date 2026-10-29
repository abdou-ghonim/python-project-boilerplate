"""Model layer.

Database first: the schema lives in sql/<dialect>/*.sql and is applied by
`flask db-apply`. Nothing here creates a table.

    base_model.py       mixins and the declarative Base the generator writes to
    models.py           GENERATED from the database by `flask generate-models`
    user.py             the account model, mapped onto your user table by config
    extended_models.py  anything else you want to hand-write

Import models from here, not from the individual modules, so that a table moving
between the generated and hand-written files does not ripple through the codebase.
"""
from app.extensions import db

from .base_model import Base, BaseModel, SerializerMixin, TimestampMixin, utcnow
from .extended_models import Item
from .user import ROLES, User

__all__ = [
    "db", "Base", "BaseModel", "SerializerMixin", "TimestampMixin", "utcnow",
    "ROLES", "User", "Item",
]
