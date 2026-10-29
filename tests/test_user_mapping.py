"""The account model is pointed at an existing table by configuration.

Nothing here builds a second User class: mapping the same table twice on one
registry is an error, and the interesting logic is in the namespace the class is
built from, which can be inspected on its own.
"""
from __future__ import annotations

import pytest
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, mapped_column

import config
from app.models import user as user_module
from app.models.base_model import SerializerMixin


def test_defaults_map_attribute_names_onto_matching_columns():
    namespace = user_module._namespace()
    assert namespace["__tablename__"] == "app_user"
    assert namespace["username"].name == "username"
    assert namespace["__mapped_fields__"] == set(user_module.COLUMNS)


def test_table_and_schema_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "AUTH_USER_TABLE", "Users")
    monkeypatch.setattr(config, "AUTH_USER_SCHEMA", "security")
    namespace = user_module._namespace()
    assert namespace["__tablename__"] == "Users"
    assert namespace["__table_args__"] == {"schema": "security"}


def test_columns_can_be_renamed(monkeypatch):
    monkeypatch.setattr(config, "AUTH_USER_COLUMNS",
                        {"username": "Email", "display_name": "FullName"})
    namespace = user_module._namespace()
    assert namespace["username"].name == "Email"
    assert namespace["display_name"].name == "FullName"
    # Everything not named keeps the attribute's own spelling.
    assert namespace["role"].name == "role"


def test_an_absent_column_becomes_a_constant(monkeypatch):
    # A table with no role column: everyone reads as AUTH_DEFAULT_ROLE, and the
    # attribute is not mapped, so no query ever asks for it.
    monkeypatch.setattr(config, "AUTH_USER_COLUMNS", {"role": "", "last_login_at": ""})
    namespace = user_module._namespace()
    assert namespace["role"] == config.AUTH_DEFAULT_ROLE
    assert namespace["last_login_at"] is None
    assert "role" not in namespace["__mapped_fields__"]
    assert "username" in namespace["__mapped_fields__"]


def test_a_column_the_app_cannot_do_without_is_refused(monkeypatch):
    monkeypatch.setattr(config, "AUTH_USER_COLUMNS", {"username": ""})
    with pytest.raises(RuntimeError, match="cannot work without"):
        user_module._namespace()


def test_touch_login_records_the_time_when_the_column_exists(user):
    assert user.last_login_at is None
    user.touch_login()
    assert user.last_login_at is not None


def test_touch_login_skips_a_table_without_the_column(user, monkeypatch):
    monkeypatch.setattr(type(user), "__mapped_fields__", frozenset({"id", "username"}))
    user.touch_login()
    assert user.last_login_at is None


def test_set_password_refuses_a_table_without_one(user, monkeypatch):
    monkeypatch.setattr(type(user), "__mapped_fields__", frozenset({"id", "username"}))
    with pytest.raises(RuntimeError, match="no password column"):
        user.set_password("something-long-enough")


def test_to_dict_uses_attribute_names_not_column_names():
    # The JSON the SPA reads must not change because the table calls a column
    # something else. Built on a registry of its own so it maps nothing real.
    class Base(DeclarativeBase):
        pass

    class Row(SerializerMixin, Base):
        __tablename__ = "legacy_row"
        id = mapped_column("RowID", Integer, primary_key=True)
        username = mapped_column("Email", String(50))
        secret = mapped_column("Pwd", String(50))
        __private__ = ("secret",)

    row = Row(id=1, username="a@b.c", secret="hunter2")
    assert row.to_dict() == {"id": 1, "username": "a@b.c"}
