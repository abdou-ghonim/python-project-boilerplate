"""The SQL schema is the source of truth, so it gets tested like code.

Two things are checked here: that the statement splitter cuts scripts where a
database would, and that the SQLite DDL and the ORM models still agree. The
second is the one that earns its keep — it is the test that fails when someone
adds a column to a model and forgets sql/.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect

from app.sql_scripts import (apply_scripts, script_dir, script_paths,
                             split_statements)

DIALECTS = ("sqlite", "postgresql", "mysql", "mssql")


@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_provider_has_schema_scripts(dialect: str) -> None:
    paths = script_paths(dialect)
    assert paths, f"no .sql files in {script_dir(dialect)}"
    assert all(split_statements(p.read_text(encoding="utf-8")) for p in paths)


def test_missing_dialect_is_an_error() -> None:
    from app.sql_scripts import SchemaScriptsNotFound

    with pytest.raises(SchemaScriptsNotFound):
        script_paths("oracle")


def test_splitter_ignores_semicolons_in_strings_and_comments() -> None:
    script = """
    -- a comment with ; in it
    CREATE TABLE t (a VARCHAR(10) DEFAULT 'x;y');
    /* another ; comment */
    INSERT INTO t (a) VALUES ('it''s; fine');
    """
    statements = split_statements(script)
    assert len(statements) == 2
    assert statements[0].endswith("'x;y')")
    assert "it''s; fine" in statements[1]


def test_splitter_uses_go_batches_when_present() -> None:
    script = """
    IF OBJECT_ID(N'dbo.t', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.t (a INT);
    END;
    GO
    CREATE INDEX ix_t_a ON dbo.t (a);
    GO
    """
    statements = split_statements(script)
    assert len(statements) == 2, statements
    assert statements[0].startswith("IF OBJECT_ID")
    assert statements[1].startswith("CREATE INDEX")


def test_splitter_drops_comment_only_fragments() -> None:
    assert split_statements("-- nothing here\n/* nor here */\n") == []


def test_sqlite_scripts_are_safe_to_rerun(sqlite_schema) -> None:
    # db-apply keeps no ledger, so re-running the directory has to be a no-op
    # rather than a pile of "already exists" errors.
    apply_scripts(sqlite_schema, script_paths("sqlite"))


def test_ddl_matches_the_models(sqlite_schema) -> None:
    from app.extensions import db
    from app import models                                      # noqa: F401

    inspector = inspect(sqlite_schema)
    present = set(inspector.get_table_names())

    for table in db.metadata.tables.values():
        assert table.name in present, f"{table.name} is not created by sql/sqlite/"

        actual = {column["name"]: column for column in inspector.get_columns(table.name)}
        assert set(actual) == {column.name for column in table.columns}, (
            f"{table.name}: the DDL and the model disagree on which columns exist")

        for column in table.columns:
            assert actual[column.name]["nullable"] == column.nullable, (
                f"{table.name}.{column.name}: nullability differs between "
                "the model and sql/sqlite/")

        expected_indexes = {index.name for index in table.indexes}
        actual_indexes = {index["name"] for index in inspector.get_indexes(table.name)}
        assert expected_indexes <= actual_indexes, (
            f"{table.name}: sql/sqlite/ is missing "
            f"{sorted(expected_indexes - actual_indexes)}")
