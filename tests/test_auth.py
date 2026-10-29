"""Local authentication, role ranking and revocation."""
from __future__ import annotations

import pytest


def test_auth_config_is_public(client):
    body = client.get("/api/auth/config").get_json()
    assert body["provider"] == "local"
    assert body["login_style"] == "password"
    # Nothing secret may appear here: the SPA reads it before signing in.
    assert "client_secret" not in str(body).lower()


def test_login_returns_a_token(client, user):
    response = client.post("/api/auth/login", json={
        "username": user.username, "password": "correct-horse-battery"})
    assert response.status_code == 200
    assert response.get_json()["token_type"] == "Bearer"


def test_wrong_password_and_unknown_user_are_indistinguishable(client, user):
    wrong = client.post("/api/auth/login", json={
        "username": user.username, "password": "nope"})
    missing = client.post("/api/auth/login", json={
        "username": "nobody@example.com", "password": "nope"})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.get_json()["error"] == missing.get_json()["error"]


def test_protected_route_requires_a_token(client):
    assert client.get("/api/items").status_code == 401


def test_protected_route_accepts_a_token(client, auth_headers):
    assert client.get("/api/items", headers=auth_headers).status_code == 200


def test_tampered_token_is_rejected(client, auth_headers):
    token = auth_headers["Authorization"].split()[1]
    forged = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    response = client.get("/api/items", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_logout_revokes_the_token(client, auth_headers):
    assert client.post("/api/auth/logout", headers=auth_headers).status_code == 200
    # Without Redis the denylist is per-process, which is exactly the case the
    # test runs in — so a revoked token must still be refused here.
    assert client.get("/api/items", headers=auth_headers).status_code == 401


def test_role_ranking_admits_higher_roles(app, client, user):
    from app.models import db

    user.role = "manager"
    db.session.commit()
    login = client.post("/api/auth/login", json={
        "username": user.username, "password": "correct-horse-battery"})
    headers = {"Authorization": f"Bearer {login.get_json()['access_token']}"}

    # manager may create (require_role("manager")) …
    created = client.post("/api/items", headers=headers, json={"name": "Widget"})
    assert created.status_code == 201
    # … but not delete (require_role("admin")).
    assert client.delete(f"/api/items/{created.get_json()['id']}",
                         headers=headers).status_code == 403


def test_disabled_account_loses_access_immediately(client, auth_headers, user):
    from app.models import db

    user.is_active = False
    db.session.commit()
    # The token is still signed and unexpired; the per-request recheck is what
    # stops it being honoured.
    assert client.get("/api/items", headers=auth_headers).status_code == 403


def test_require_role_rejects_unknown_roles():
    from app.auth import require_role

    with pytest.raises(ValueError, match="Unknown role"):
        require_role("superuser")


def test_password_minimum_length_enforced(app):
    from app.models import User

    with pytest.raises(ValueError, match="at least"):
        User(username="short@example.com").set_password("abc")
