"""The JWT every provider issues, and the denylist that makes logout mean something.

Providers differ in how they establish who you are; once established, they all
mint the same token. That is what lets @require_auth, the frontend interceptor
and every route stay unaware of which provider is configured.

A JWT is valid until it expires because nothing consults a database to check —
that is the point of a stateless token, and it means logout is cosmetic unless
something records the revocation. Redis is the right store: an entry only has to
outlive the token, so it expires itself, and every worker sees the same list.
Without Redis the list is per-process; the app says so rather than pretending,
and REDIS_REQUIRED=true (the default outside development) makes it a boot
failure instead.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from flask import current_app

import config
from app.redis import get_redis, key

logger = logging.getLogger(__name__)

#: Fallback denylist for when Redis is absent. Process-local, so it is a
#: development convenience and nothing more.
_local: set[str] = set()


class TokenError(Exception):
    """Any token that cannot be trusted, with a client-safe message."""


def issue_token(identity: dict, *, expires_minutes: int | None = None) -> dict:
    """Mint a signed JWT for an identity dict (see User.identity)."""
    now = datetime.now(timezone.utc)
    minutes = expires_minutes or config.JWT_EXPIRY_MINUTES
    expires = now + timedelta(minutes=minutes)

    claims = {
        **identity,
        # A unique id per token is what makes revocation possible at all: the
        # denylist stores jti, so logout invalidates this token and not the
        # user's other sessions.
        "jti": uuid.uuid4().hex,
        "iat": now,
        "nbf": now,
        "exp": expires,
        "iss": config.JWT_ISSUER,
        "aud": config.JWT_AUDIENCE,
    }
    token = jwt.encode(claims, current_app.config["SECRET_KEY"],
                       algorithm=config.JWT_ALGORITHM)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": minutes * 60,
        "expires_at": expires.isoformat(),
        "user": {k: v for k, v in identity.items() if k != "sub"}
                | {"id": identity.get("sub")},
    }


def decode_token(token: str) -> dict:
    """Verify a token and return its claims, or raise TokenError.

    `algorithms` is pinned to the configured algorithm rather than read from the
    token's own header — accepting the header's claim is how "alg: none" and
    HS256-signed-with-the-RSA-public-key forgeries work.
    """
    try:
        claims = jwt.decode(
            token,
            current_app.config["SECRET_KEY"],
            algorithms=[config.JWT_ALGORITHM],
            issuer=config.JWT_ISSUER,
            audience=config.JWT_AUDIENCE,
            leeway=config.JWT_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Session expired. Please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        # The specific reason stays in the log; the client gets one message, so
        # that probing cannot distinguish a wrong audience from a bad signature.
        logger.warning("Rejected token: %s", exc)
        raise TokenError("Invalid authentication token.") from exc

    if is_revoked(claims["jti"]):
        raise TokenError("Session has been signed out.")

    # A per-user cut-off invalidates tokens whose jti we never saw — set when an
    # account is disabled or its role changes, where every existing session must
    # stop rather than run on with stale privileges until it expires.
    cutoff = user_revoked_at(str(claims.get("sub")))
    if cutoff is not None and int(claims.get("iat", 0)) < cutoff:
        raise TokenError("Session is no longer valid. Please sign in again.")
    return claims


def revoke_token(claims: dict) -> None:
    """Deny-list one token for whatever remains of its lifetime."""
    expires = claims.get("exp")
    ttl = (max(1, int(expires - datetime.now(timezone.utc).timestamp())) if expires
           else config.JWT_EXPIRY_MINUTES * 60)
    jti = claims["jti"]

    client = get_redis()
    if client is None:
        _local.add(jti)
        logger.warning(
            "Token %s revoked in this process only — no Redis, so other workers "
            "will keep accepting it until it expires.", jti[:8])
        return
    try:
        client.set(key("revoked", jti), "1", ex=ttl)
    except Exception as exc:                                    # noqa: BLE001
        _local.add(jti)
        logger.error("Could not record revocation for %s in Redis: %s", jti[:8], exc)


def is_revoked(jti: str) -> bool:
    if jti in _local:
        return True
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.exists(key("revoked", jti)))
    except Exception as exc:                                    # noqa: BLE001
        # Fail closed: an unreachable denylist means we cannot prove the token is
        # still valid, and treating "unknown" as "fine" is how a revoked session
        # keeps working through an outage.
        logger.error("Revocation check failed for %s, refusing the token: %s",
                     jti[:8], exc)
        return True


def revoke_all_for_user(user_id: str, ttl_seconds: int | None = None) -> None:
    """Invalidate every token for one user by recording a cut-off timestamp.

    Used when an account is disabled or a role changes: the individual jti values
    are unknown, so decode_token compares each token's iat against this marker.
    """
    client = get_redis()
    if client is None:
        logger.warning("No Redis: cannot revoke all sessions for user %s.", user_id)
        return
    ttl = ttl_seconds or config.JWT_EXPIRY_MINUTES * 60
    try:
        client.set(key("revoked-user", user_id), str(int(time.time())), ex=ttl)
    except Exception as exc:                                    # noqa: BLE001
        logger.error("Could not revoke sessions for user %s: %s", user_id, exc)


def user_revoked_at(user_id: str) -> int | None:
    client = get_redis()
    if client is None:
        return None
    try:
        raw = client.get(key("revoked-user", user_id))
        return int(raw) if raw else None
    except Exception:                                           # noqa: BLE001
        return None
