"""Test fixtures.

Tests run against SQLite in a temporary file with auth, Redis and rate limiting
in their development configuration: the point is to exercise the wiring, not to
require a database server and a Redis to run the suite.

The schema comes from sql/sqlite/*.sql rather than from `db.create_all()`,
because that is where the schema comes from everywhere else. A column added to
a model and forgotten in the DDL then fails the whole suite rather than only
production.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

# Set before config.py is imported — it reads the environment at import time.
os.environ.setdefault("FLASK_ENV", "test")
os.environ.setdefault("DB_PROVIDER", "sqlite")
os.environ.setdefault("AUTH_PROVIDER", "local")
os.environ.setdefault("REDIS_REQUIRED", "false")
os.environ.setdefault("LOG_TO_FILE", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-bytes-long!!")
# Where a real Redis is reachable the suite uses it, under a prefix of its own:
# rate-limit counters and the revocation list are shared, durable state, and a
# previous run's keys would otherwise decide this run's results.
os.environ["REDIS_KEY_PREFIX"] = f"test-{uuid.uuid4().hex[:8]}"


def _flush_redis() -> None:
    """Drop this run's keys. A no-op when Redis is not available."""
    import config
    from app.redis import get_redis

    client = get_redis()
    if client is None:
        return
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match=f"{config.REDIS_KEY_PREFIX}:*",
                                   count=500)
        if keys:
            client.delete(*keys)
        if cursor == 0:
            return


@pytest.fixture()
def app(tmp_path: Path):
    # Imported inside the fixture: config.py reads the environment when it is
    # first imported, and the defaults above have to be in place by then.
    from app import create_app
    from app.extensions import db
    from app.sql_scripts import apply_scripts, script_paths

    handle, db_path = tempfile.mkstemp(suffix=".db", dir=tmp_path)
    os.close(handle)

    application = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
    })
    with application.app_context():
        apply_scripts(db.engine, script_paths("sqlite"))
        _flush_redis()
        # In-process fallbacks are module state and outlive the app, so they are
        # cleared alongside Redis.
        from app import redis
        from app.auth import tokens
        tokens._local.clear()
        redis._rate_local.clear()

        yield application

        _flush_redis()
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def sqlite_schema(tmp_path: Path):
    """A fresh SQLite database with sql/sqlite/*.sql applied, and nothing else.

    No Flask app, so the schema can be examined without Redis or an auth
    provider being involved in the answer.
    """
    from sqlalchemy import create_engine

    from app.sql_scripts import apply_scripts, script_paths

    engine = create_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    apply_scripts(engine, script_paths("sqlite"))
    yield engine
    engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def user(app):
    """An active admin with a known password."""
    from app.models import User, db

    account = User(username="admin@example.com", email="admin@example.com",
                   display_name="Admin", role="admin", auth_provider="local")
    account.set_password("correct-horse-battery")
    db.session.add(account)
    db.session.commit()
    return account


@pytest.fixture()
def auth_headers(client, user):
    response = client.post("/api/auth/login", json={
        "username": user.username, "password": "correct-horse-battery"})
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['access_token']}"}
