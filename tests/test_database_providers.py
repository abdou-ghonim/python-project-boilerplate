"""Each dialect builds a URI its driver would accept, and judges encryption."""
from __future__ import annotations

import pytest

import config
from app import database


@pytest.fixture()
def db_settings(monkeypatch):
    monkeypatch.setattr(config, "DB_HOST", "db.internal")
    monkeypatch.setattr(config, "DB_PORT", None)
    monkeypatch.setattr(config, "DB_NAME", "appdb")
    monkeypatch.setattr(config, "DB_USER", "svc")
    # Punctuation that breaks an un-encoded URI, which is the common case.
    monkeypatch.setattr(config, "DB_PASSWORD", "p@ss:w/rd")
    monkeypatch.setattr(config, "DB_OPTIONS", "")
    monkeypatch.setattr(config, "DATABASE_URI_OVERRIDE", "")
    monkeypatch.setattr(config, "DB_REQUIRE_TLS", True)
    monkeypatch.setattr(config, "DB_VERIFY_CERT", True)


@pytest.fixture()
def as_dialect(monkeypatch):
    """Switch DB_PROVIDER. Nothing is cached, so this is all it takes."""
    def _select(name: str) -> None:
        monkeypatch.setattr(config, "DB_PROVIDER", name)
    return _select


@pytest.mark.parametrize("name,prefix", [
    ("postgresql", "postgresql+psycopg://"),
    ("mysql", "mysql+pymysql://"),
    ("mssql", "mssql+pyodbc://"),
])
def test_uri_shape_and_password_encoding(db_settings, as_dialect, name, prefix):
    as_dialect(name)
    uri = database.uri()
    assert uri.startswith(prefix)
    # The raw password must never appear: @ : / would re-parse the URI.
    assert "p@ss:w/rd" not in uri
    assert "p%40ss%3Aw%2Frd" in uri
    assert "db.internal" in uri and "appdb" in uri


@pytest.mark.parametrize("name", ["postgresql", "mysql", "mssql"])
def test_tls_required_uri_passes_its_own_check(db_settings, as_dialect, name):
    as_dialect(name)
    database.check_transport_security(database.uri(), development=False)


@pytest.mark.parametrize("name,plaintext", [
    ("postgresql", "postgresql+psycopg://u:p@h/db?sslmode=disable"),
    ("mysql", "mysql+pymysql://u:p@h/db?charset=utf8mb4"),
    ("mssql", "mssql+pyodbc://u:p@h/db?driver=ODBC+Driver+18"),
])
def test_unencrypted_connection_is_fatal_outside_development(
        db_settings, as_dialect, name, plaintext):
    as_dialect(name)
    with pytest.raises(RuntimeError, match="not encrypted"):
        database.check_transport_security(plaintext, development=False)
    # Development only warns, so a local docker-compose database still works.
    database.check_transport_security(plaintext, development=True)


def test_uri_override_wins(monkeypatch, db_settings, as_dialect):
    as_dialect("postgresql")
    monkeypatch.setattr(config, "DATABASE_URI_OVERRIDE", "postgresql+psycopg://managed/db")
    assert database.uri() == "postgresql+psycopg://managed/db"


def test_sqlite_takes_no_pool_arguments(as_dialect):
    # SQLite's pool classes reject pool_size, so a stray default here is a
    # TypeError on the first connection rather than a warning.
    as_dialect("sqlite")
    assert "pool_size" not in database.engine_options()


@pytest.mark.parametrize("spelling,canonical", [
    ("postgres", "postgresql"), ("sqlserver", "mssql"), ("mariadb", "mysql"),
])
def test_dialect_aliases(spelling, canonical):
    assert database.dialect(spelling).name == canonical


def test_unknown_dialect_is_refused():
    with pytest.raises(RuntimeError, match="not a known database"):
        database.dialect("oracle")
