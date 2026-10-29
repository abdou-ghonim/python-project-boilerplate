"""`flask generate-models` has to produce a file that actually imports.

The generator emits a fixed `from app.models.base_model import Base` header, so
the name it reaches for is part of this project's contract with it. Nothing else
in the codebase imports that name, which is exactly why it is worth a test: it
would otherwise be noticed only by whoever first points the boilerplate at a
real database.
"""
from __future__ import annotations

import ast
import importlib

import pytest
from sqlalchemy import MetaData


@pytest.fixture()
def generated_code(sqlite_schema) -> str:
    from lib import DeclarativeGenerator

    metadata = MetaData()
    metadata.reflect(sqlite_schema)
    return DeclarativeGenerator(metadata, sqlite_schema, set()).generate()


def test_generated_code_is_valid_python(generated_code: str) -> None:
    compile(generated_code, "<generated>", "exec")
    assert "class AppUser(Base)" in generated_code


def test_generated_imports_all_resolve(generated_code: str) -> None:
    for node in ast.walk(ast.parse(generated_code)):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        module = importlib.import_module(node.module)
        for alias in node.names:
            assert hasattr(module, alias.name), (
                f"the generator emits `from {node.module} import {alias.name}`, "
                f"which does not exist")


def test_generated_models_are_off_the_flask_sqlalchemy_metadata() -> None:
    # Generated classes map tables the database already owns. Were they on
    # db.metadata, `flask db-init --drop` would drop them.
    from app.extensions import db
    from app.models.base_model import Base

    assert Base.metadata is not db.metadata
