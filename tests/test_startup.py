"""The startup checks that are meant to be fatal actually are."""
from __future__ import annotations

import pytest

import config


def test_health_reports_providers(client):
    body = client.get("/health").get_json()
    assert body["status"] in ("ok", "degraded")
    assert body["checks"]["database"]["connected"] is True
    assert body["checks"]["database"]["provider"] == "sqlite"


def test_placeholder_secret_key_is_refused(monkeypatch):
    from app import create_app

    monkeypatch.setattr(config, "SECRET_KEY", config.INSECURE_SECRET_KEY)
    with pytest.raises(RuntimeError, match="placeholder"):
        create_app()


def test_short_secret_key_is_refused(monkeypatch):
    from app import create_app

    monkeypatch.setattr(config, "SECRET_KEY", "too-short")
    with pytest.raises(RuntimeError, match="32"):
        create_app()


def test_unknown_auth_provider_is_refused():
    from app.auth import get_auth_provider

    with pytest.raises(RuntimeError, match="not a known provider"):
        get_auth_provider("ldap")


def test_security_headers_present(client):
    headers = client.get("/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers.get(config.LOG_REQUEST_HEADER)
