"""The account model, mapped onto whatever user table you already have.

Database first means the table is rarely called `app_user` with exactly these
column names, so the mapping is configuration rather than source:

    AUTH_USER_TABLE=Users
    AUTH_USER_SCHEMA=security
    AUTH_USER_COLUMNS=username=Email,display_name=FullName,role=,last_login_at=

An attribute with nothing after the `=` is a column the table does not have.
The model keeps the attribute as a constant instead, so the rest of the code —
which only ever says `user.role` or `user.is_active` — carries on working
against a table that has no such column. `username`, the primary key and the
password hash cannot be dropped that way if you want local logins.

The class is assembled with `type()` rather than written out, because a column
that may or may not exist cannot be expressed as a class body. Everything about
which columns there are is in COLUMNS and ABSENT_DEFAULTS below.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

import config
from app.extensions import db

from .base_model import SerializerMixin, utcnow

#: Roles understood by @require_role, least privileged first (see config.ROLES).
ROLES = config.ROLES

#: attribute -> how to map it, given the column name it ended up with.
COLUMNS = {
    "id": lambda name: mapped_column(name, Integer, primary_key=True,
                                     autoincrement=True),
    "username": lambda name: mapped_column(name, String(255), nullable=False,
                                           unique=True, index=True),
    "email": lambda name: mapped_column(name, String(255), index=True),
    "display_name": lambda name: mapped_column(name, String(255)),
    # Null for a federated user: there is no local password to check, and a
    # nullable column says that more clearly than an unusable placeholder hash.
    "password_hash": lambda name: mapped_column(name, String(512)),
    "role": lambda name: mapped_column(name, String(32), nullable=False,
                                       default=config.AUTH_DEFAULT_ROLE),
    "is_active": lambda name: mapped_column(name, Boolean, nullable=False,
                                            default=True),
    "auth_provider": lambda name: mapped_column(name, String(32), nullable=False,
                                                default="local"),
    "external_id": lambda name: mapped_column(name, String(255), index=True),
    "last_login_at": lambda name: mapped_column(name, DateTime(timezone=True)),
    "created_at": lambda name: mapped_column(name, DateTime(timezone=True),
                                             server_default=func.now(),
                                             nullable=False),
    "updated_at": lambda name: mapped_column(name, DateTime(timezone=True),
                                             server_default=func.now(),
                                             onupdate=func.now(), nullable=False),
}

#: What an attribute reads as when its column is absent. An attribute missing
#: from here is one the application cannot do without.
ABSENT_DEFAULTS = {
    "email": None, "display_name": None, "password_hash": None,
    "role": config.AUTH_DEFAULT_ROLE, "is_active": True,
    "auth_provider": "local", "external_id": None, "last_login_at": None,
    "created_at": None, "updated_at": None,
}


class UserBehaviour:
    """Everything about an account that is not a column.

    Kept separate from the mapping so that the generated-or-configured half
    above stays a table of data rather than a class with logic hidden in it.
    """

    #: Attributes that are really columns on this table. The rest are constants.
    __mapped_fields__: frozenset[str] = frozenset()

    def set_password(self, password: str) -> None:
        """Hash and store a password, enforcing the configured minimum length.

        Werkzeug's default (scrypt) is used rather than a bcrypt/argon2
        dependency: it is memory-hard, already installed with Flask, and the
        stored hash records its own parameters, so raising the cost later does
        not invalidate existing rows.
        """
        if "password_hash" not in self.__mapped_fields__:
            raise RuntimeError(
                "This user table has no password column (AUTH_USER_COLUMNS says "
                "password_hash is absent), so passwords cannot be set here. Use "
                "AUTH_PROVIDER=oidc, or point AUTH_USER_COLUMNS at the real one.")
        if len(password) < config.PASSWORD_MIN_LENGTH:
            raise ValueError(
                f"Password must be at least {config.PASSWORD_MIN_LENGTH} characters.")
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def touch_login(self) -> None:
        if "last_login_at" in self.__mapped_fields__:
            self.last_login_at = utcnow()

    @property
    def identity(self) -> dict:
        """The claims an auth provider puts in the JWT."""
        return {
            "sub": str(self.id),
            "username": self.username,
            "email": self.email,
            "name": self.display_name or self.username,
            "role": self.role,
            "provider": self.auth_provider,
        }

    def __repr__(self) -> str:                                  # pragma: no cover
        return f"<User {getattr(self, 'username', None)!r}>"


def _column_name(attribute: str) -> str | None:
    """The column backing `attribute`, or None when the table has not got one."""
    if attribute not in config.AUTH_USER_COLUMNS:
        return attribute                        # same name as the attribute
    return config.AUTH_USER_COLUMNS[attribute] or None


def _namespace() -> dict:
    namespace: dict = {
        "__tablename__": config.AUTH_USER_TABLE,
        "__private__": ("password_hash",),
    }
    if config.AUTH_USER_SCHEMA:
        namespace["__table_args__"] = {"schema": config.AUTH_USER_SCHEMA}

    mapped: list[str] = []
    for attribute, build in COLUMNS.items():
        column = _column_name(attribute)
        if column:
            namespace[attribute] = build(column)
            mapped.append(attribute)
        elif attribute in ABSENT_DEFAULTS:
            namespace[attribute] = ABSENT_DEFAULTS[attribute]
        else:
            raise RuntimeError(
                f"AUTH_USER_COLUMNS marks {attribute!r} as absent, but the "
                "application cannot work without it.")

    namespace["__mapped_fields__"] = frozenset(mapped)
    return namespace


#: An account. Query it like any other model; `db.session.get(User, 1)`.
User = type("User", (UserBehaviour, SerializerMixin, db.Model), _namespace())
