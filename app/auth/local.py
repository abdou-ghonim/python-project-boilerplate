"""Username and password, checked against the configured user table."""
from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request

import config
from app.models import User, db
from app.redis import client_ip, hit_window, rate_limit, reset_limit

from . import AuthError, AuthProvider, bearer_token, require_auth
from .tokens import TokenError, decode_token, issue_token, revoke_token

logger = logging.getLogger(__name__)


class LocalAuthProvider(AuthProvider):
    name = "local"
    login_style = "password"

    def init_app(self, app) -> None:
        if config.DEFAULT_ADMIN_PASSWORD == config.INSECURE_ADMIN_PASSWORD \
                and not config.is_development(bool(app.config.get("TESTING"))):
            # Not fatal — a deployment that created its admin properly has no
            # reason to set this — but the seeding commands refuse to use the
            # placeholder outside development, and that is worth saying once.
            logger.warning(
                "DEFAULT_ADMIN_PASSWORD is still the placeholder. `flask db-apply` "
                "and `flask create-admin` will refuse to seed an admin account "
                "until it is set to a real password.")

    def register_routes(self, bp: Blueprint) -> None:
        @bp.post("/login")
        @rate_limit(lambda: config.RATE_LIMIT_LOGIN, by="ip", scope="auth-login")
        def login():
            payload = request.get_json(silent=True) or {}
            username = (payload.get("username") or payload.get("email") or "").strip()
            password = payload.get("password") or ""
            if not username or not password:
                raise AuthError("Username and password are required.", 400)

            # Per-account lockout on top of the per-IP limit above: one stops a
            # single host hammering the endpoint, the other stops a distributed
            # attempt at one account. Both counters live in Redis, so they hold
            # across workers and restarts.
            bucket = f"auth-login-user:{username.lower()}"
            allowed, _, retry_after = hit_window(
                bucket, config.LOGIN_MAX_ATTEMPTS, config.LOGIN_LOCKOUT_SECONDS)
            if not allowed:
                logger.warning("Account %s is locked out after repeated failures",
                               username)
                raise AuthError(
                    f"Too many failed attempts. Try again in {retry_after} seconds.",
                    429)

            user = db.session.query(User).filter(
                db.func.lower(User.username) == username.lower()).one_or_none()

            # One message for "no such user" and "wrong password": distinguishing
            # them turns the login form into an account-enumeration oracle.
            if user is None or not user.check_password(password):
                logger.info("Failed login for %r from %s", username, client_ip())
                raise AuthError("Invalid username or password.")
            if not user.is_active:
                raise AuthError("This account has been disabled.", 403)

            reset_limit(bucket, config.LOGIN_LOCKOUT_SECONDS)
            user.touch_login()
            db.session.commit()
            logger.info("User %s signed in", user.username)
            return jsonify(issue_token(user.identity))

        @bp.post("/logout")
        def logout():
            # Revocation needs the token's own claims, so this is deliberately
            # not behind @require_auth: an expired token should log out cleanly
            # rather than answer 401.
            token = bearer_token()
            if token:
                try:
                    revoke_token(decode_token(token))
                except TokenError:
                    pass                    # already invalid: nothing to revoke
            return jsonify({"status": "signed out"})

        @bp.get("/me")
        @require_auth
        def me():
            user = db.session.get(User, int(g.current_user["sub"]))
            if user is None or not user.is_active:
                raise AuthError("This account is no longer active.", 403)
            return jsonify(user.to_dict())

        @bp.post("/change-password")
        @require_auth
        def change_password():
            payload = request.get_json(silent=True) or {}
            user = db.session.get(User, int(g.current_user["sub"]))
            if user is None \
                    or not user.check_password(payload.get("current_password") or ""):
                raise AuthError("Current password is incorrect.")
            try:
                user.set_password(payload.get("new_password") or "")
            except ValueError as exc:
                raise AuthError(str(exc), 400) from exc
            db.session.commit()
            logger.info("Password changed for %s", user.username)
            return jsonify({"status": "password changed"})

    def authenticate_request(self, claims: dict) -> dict:
        """Confirm the account still exists and is active.

        A signature proves the token was ours when issued; it says nothing about
        whether the account was disabled five minutes ago. One primary-key lookup
        per request is a fair price for a disabled account losing access now
        rather than at token expiry.
        """
        user = db.session.get(User, int(claims.get("sub", 0) or 0))
        if user is None or not user.is_active:
            raise AuthError("This account is no longer active.", 403)
        # Role changes take effect on the next request, not the next login.
        claims["role"] = user.role
        return claims
