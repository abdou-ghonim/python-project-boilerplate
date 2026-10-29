"""Who the caller is, and what they may do.

    tokens.py   the JWT everything downstream speaks, and the revocation list
    local.py    username and password, checked against the user table
    oidc.py     OpenID Connect against an external IdP

Providers differ only in how identity is established. Everything after that —
the JWT, @require_auth, the frontend — is the same whichever is configured, so
swapping local passwords for corporate SSO is a config change, not a rewrite.
The `none` provider lives in this file, because it is twenty lines and exists
only to be refused outside development.
"""
from __future__ import annotations

import logging
from functools import wraps
from importlib import import_module

from flask import Blueprint, Flask, g, jsonify, request

import config
from app.models import ROLES

from .tokens import (TokenError, decode_token, issue_token, revoke_all_for_user,
                     revoke_token)

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """An authentication failure with a message that is safe to show a client."""

    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message = message
        self.status = status


class AuthProvider:
    """Establishes who the caller is, then hands back a standard identity dict.

    A plain class, not an ABC: there are three implementations, they are all in
    this package, and an abstract base buys nothing that `NotImplementedError`
    does not.
    """

    #: Value of AUTH_PROVIDER that selects this class.
    name: str = ""
    #: Shown to the SPA by GET /api/auth/config so one Login page serves all three.
    login_style: str = "password"               # password | redirect | none

    def init_app(self, app: Flask) -> None:
        """Validate configuration and set up clients. Raise to refuse startup."""

    def register_routes(self, bp: Blueprint) -> None:
        """Attach the provider's own endpoints under /api/auth."""
        raise NotImplementedError

    def public_config(self) -> dict:
        """Non-secret description of this provider, for the SPA."""
        return {"provider": self.name, "login_style": self.login_style}

    def authenticate_request(self, claims: dict) -> dict:
        """Last word on a decoded token, per request.

        The default trusts the signed claims. Override to re-check live state —
        a disabled account, a changed role — where a valid signature alone should
        not be enough.
        """
        return claims


ANONYMOUS = {"sub": "0", "username": "anonymous", "email": None,
             "name": "Anonymous", "role": "admin", "provider": "none"}


class NoAuthProvider(AuthProvider):
    """No authentication at all — for an internal tool behind another gate.

    Refuses to load outside development. A deployment that genuinely wants this
    has a network boundary doing the work, and should say so explicitly rather
    than inherit it from an environment variable copied between configs.
    """

    name = "none"
    login_style = "none"

    def init_app(self, app: Flask) -> None:
        if not config.is_development(bool(app.config.get("TESTING"))):
            raise RuntimeError(
                "AUTH_PROVIDER=none disables authentication entirely, and every "
                f"request is treated as an admin. FLASK_ENV is {config.ENVIRONMENT!r}, "
                "which is not a development environment. Set AUTH_PROVIDER to local "
                "or oidc.")
        logger.warning("SECURITY: AUTH_PROVIDER=none — every request is treated as "
                       "an authenticated admin. Development only.")

    def register_routes(self, bp: Blueprint) -> None:
        @bp.get("/me")
        def me():
            return jsonify(ANONYMOUS)

        @bp.post("/logout")
        def logout():
            return jsonify({"status": "no session to end"})

    def public_config(self) -> dict:
        return {**super().public_config(), "anonymous_identity": ANONYMOUS}


#: AUTH_PROVIDER value → where to find the class. Imported only when selected,
#: so an install that never uses SSO never imports Authlib.
PROVIDERS: dict[str, str | None] = {
    "local": "app.auth.local:LocalAuthProvider",
    "oidc": "app.auth.oidc:OIDCAuthProvider",
    "none": None,                               # NoAuthProvider, defined above
}

ALIASES = {"password": "local", "db": "local", "database": "local",
           "sso": "oidc", "openid": "oidc", "oauth": "oidc",
           "disabled": "none", "off": "none"}

#: Cached because the OIDC provider holds a configured Authlib client; the other
#: two are stateless and would not care.
_provider: AuthProvider | None = None


def get_auth_provider(name: str | None = None) -> AuthProvider:
    """The configured provider (cached), or the one explicitly named."""
    global _provider
    if name is None and _provider is not None:
        return _provider

    key = (name or config.AUTH_PROVIDER).strip().lower()
    key = ALIASES.get(key, key)
    if key not in PROVIDERS:
        raise RuntimeError(
            f"AUTH_PROVIDER={key!r} is not a known provider. "
            f"Choose one of: {', '.join(sorted(PROVIDERS))}.")

    target = PROVIDERS[key]
    if target is None:
        provider: AuthProvider = NoAuthProvider()
    else:
        module_path, _, class_name = target.partition(":")
        provider = getattr(import_module(module_path), class_name)()

    if name is None:
        _provider = provider
    return provider


def reset_provider_cache() -> None:
    """Drop the cached provider. Tests that switch AUTH_PROVIDER need this."""
    global _provider
    _provider = None


# ── Route guards ─────────────────────────────────────────────────────────────
def bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def load_identity() -> dict | None:
    """Decode the bearer token if present. Claims, or None when absent."""
    token = bearer_token()
    if not token:
        return None
    return get_auth_provider().authenticate_request(decode_token(token))


def require_auth(view):
    """Refuse the request unless it carries a valid, unrevoked token."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        provider = get_auth_provider()
        if provider.name == "none":
            # Refused at startup outside development, so reaching here means
            # someone deliberately turned authentication off.
            g.current_user = ANONYMOUS
            return view(*args, **kwargs)

        try:
            claims = load_identity()
        except AuthError as exc:
            # The provider decides the status: a disabled account is a 403, not
            # a 401 the client could fix by signing in again.
            return _unauthorized(exc.message, exc.status)
        except TokenError as exc:
            return _unauthorized(str(exc))
        if claims is None:
            return _unauthorized("Authentication required.")

        g.current_user = claims
        return view(*args, **kwargs)

    return wrapper


def require_role(*roles: str):
    """Require one of `roles`. Implies @require_auth.

    Roles are ranked, so require_role("manager") also admits an admin —
    otherwise every guard would have to list every role above it, and the one
    that forgets is a privilege bug nobody notices.
    """
    unknown = set(roles) - set(ROLES)
    if unknown:
        raise ValueError(f"Unknown role(s) {sorted(unknown)}; known roles are {ROLES}.")
    minimum = min(ROLES.index(r) for r in roles)

    def decorator(view):
        @wraps(view)
        @require_auth
        def wrapper(*args, **kwargs):
            role = (g.current_user or {}).get("role", "")
            rank = ROLES.index(role) if role in ROLES else -1
            if rank < minimum:
                logger.warning(
                    "Role check failed on %s: %s has role %r, needs %s",
                    request.path, (g.current_user or {}).get("username"), role,
                    " or ".join(roles))
                return _unauthorized("You do not have access to this resource.", 403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def current_user() -> dict:
    """Claims for the authenticated caller, or {} on an anonymous request."""
    return getattr(g, "current_user", None) or {}


def _unauthorized(message: str, status: int = 401):
    response = jsonify({"error": message, "status": status})
    response.status_code = status
    if status == 401:
        # Tells a client this is an authentication problem it can fix by signing
        # in, rather than a permanent refusal.
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


__all__ = [
    "ANONYMOUS", "AuthError", "AuthProvider", "PROVIDERS", "TokenError",
    "bearer_token", "current_user", "decode_token", "get_auth_provider",
    "issue_token", "require_auth", "require_role", "reset_provider_cache",
    "revoke_all_for_user", "revoke_token",
]
