"""Application factory.

Reading create_app() top to bottom should tell you everything about how this
application starts: what it refuses to start without, which backends it is
wired to, and which cross-cutting behaviour every request passes through.

Startup checks here are deliberately fatal. Each one guards a failure that is
invisible at runtime — a forgeable signing key, an unencrypted database link,
rate limiting that silently stops limiting — and for those, a warning in a log
nobody reads is not a control.
"""
from __future__ import annotations

import logging
from datetime import datetime

from flask import Flask, g, request
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS

import config
from app.extensions import db
from app.auth import get_auth_provider
from app.errors import register_error_handlers
from app.logging_setup import (clear_request_id, configure_logging, get_request_id,
                               set_request_id)

logger = logging.getLogger(__name__)

__all__ = ["create_app", "db"]


def _resolve_secret_key(app: Flask) -> str:
    """Return the signing key, failing closed on an unset or weak value.

    A guessable SECRET_KEY lets anyone forge a JWT, including one claiming
    role=admin. Length is fatal rather than a warning: a short HMAC key is
    brute-forceable offline from a single captured token, and PyJWT's own warning
    below 32 bytes stops nothing from serving traffic.
    """
    if app.config.get("TESTING"):
        return app.config.get("SECRET_KEY") or config.SECRET_KEY

    key = config.SECRET_KEY
    if not key or key == config.INSECURE_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY is unset or still the placeholder. Generate one with "
            "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
            "and set it in the environment before starting."
        )
    if len(key.encode()) < 32:
        raise RuntimeError(
            f"SECRET_KEY is {len(key.encode())} bytes; at least 32 are required."
        )
    return key


class _JSONProvider(DefaultJSONProvider):
    """Serialise datetimes as ISO 8601 instead of Flask's RFC 822 default.

    Flask renders a datetime as "Tue, 06 Oct 2026 14:07:05 GMT", which a browser
    shifts by its UTC offset. An ISO string round-trips through `new Date()`
    unchanged, which is what every frontend here expects.
    """

    sort_keys = config.JSON_SORT_KEYS

    @staticmethod
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


def _parse_cors_origins() -> list[str] | str:
    raw = (config.CORS_ORIGINS or "").strip()
    if not raw:
        return []                           # same-origin only
    if raw == "*":
        return "*"
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def _build_csp() -> str:
    """Content-Security-Policy for the SPA.

    'unsafe-inline' is allowed for styles only: Vite emits a stylesheet, but
    component libraries set style= attributes, which CSP counts as inline.
    Scripts get no such exemption — that is the directive that matters for XSS.
    """
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' data: https://fonts.gstatic.com",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ])


def create_app(test_config: dict | None = None) -> Flask:
    configure_logging()

    app = Flask(__name__, static_folder=str(config.BASE_DIR / "frontend" / "dist"))
    app.json = _JSONProvider(app)
    app.config.update(
        SECRET_KEY=config.SECRET_KEY,
        MAX_CONTENT_LENGTH=config.MAX_CONTENT_LENGTH,
        APP_NAME=config.APP_NAME,
        APP_VERSION=config.APP_VERSION,
    )
    if test_config:
        app.config.update(test_config)

    app.config["SECRET_KEY"] = _resolve_secret_key(app)
    testing = bool(app.config.get("TESTING"))
    development = config.is_development(testing)

    # ── Database ─────────────────────────────────────────────────────────────
    # The provider owns the URI, the engine tuning and the transport check; this
    # function only decides when they happen.
    from app import database

    database.ensure_driver()
    uri = app.config.get("SQLALCHEMY_DATABASE_URI") or database.uri()
    database.check_transport_security(uri, development=development)
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = database.engine_options()
    db.init_app(app)

    # Imported for their side effect: a model class that is never imported is
    # not on the metadata, and nothing downstream — the mapper registry, the
    # `flask db-check` schema report — can see the table it maps.
    from app import models                                      # noqa: F401

    # ── Redis ────────────────────────────────────────────────────────────────
    # Touched at startup so an unreachable server is a boot failure here rather
    # than a surprise on the first rate-limited request. A no-op, and no
    # connection attempt at all, when REDIS_ENABLED=false.
    from app.redis import get_redis
    get_redis()

    # ── Authentication ───────────────────────────────────────────────────────
    auth = get_auth_provider()
    auth.init_app(app)
    app.extensions["auth_provider"] = auth
    logger.info("Auth: %s | Database: %s", auth.name, database.dialect().name)

    # ── Request lifecycle ────────────────────────────────────────────────────
    @app.before_request
    def _begin_request():
        # Honour an upstream id when a proxy already assigned one, so a trace
        # spans the whole hop chain rather than restarting here.
        set_request_id(request.headers.get(config.LOG_REQUEST_HEADER))
        g.started_at = datetime.now()

    @app.after_request
    def _finish_request(resp):
        resp.headers.setdefault(config.LOG_REQUEST_HEADER, get_request_id())
        if request.path.startswith("/api/"):
            duration = (datetime.now() - getattr(g, "started_at", datetime.now()))
            logger.info("%s %s → %s (%dms)", request.method, request.path,
                        resp.status_code, duration.total_seconds() * 1000)
        return resp

    @app.teardown_request
    def _end_request(exc):
        clear_request_id()

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Explicit allow-list only. A wildcard origin with credentials is refused
    # rather than quietly accepted: browsers reject that pairing anyway, and
    # configuring it signals a misunderstanding worth stopping at startup.
    origins = _parse_cors_origins()
    if origins == "*":
        if not development:
            raise RuntimeError(
                "CORS_ORIGINS=* outside development. List the browser origins that "
                "may call this API explicitly."
            )
        CORS(app, origins="*", supports_credentials=False)
    elif origins:
        CORS(app, origins=origins, supports_credentials=True)
    # else: no CORS headers at all — the production image serves the SPA itself.

    # ── Security headers ─────────────────────────────────────────────────────
    csp = _build_csp()

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Content-Security-Policy", csp)
        # HSTS only over TLS: it is ignored on plain HTTP, and pinning localhost
        # to HTTPS during development is a nuisance to undo in a browser.
        forwarded = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
        if request.is_secure or forwarded == "https":
            resp.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
        return resp

    register_error_handlers(app)

    from app.api import register_api
    register_api(app)

    from app.routes import main
    app.register_blueprint(main)

    from cli import register_commands
    register_commands(app)

    logger.info("%s %s ready (%s)", config.APP_NAME, config.APP_VERSION,
                config.ENVIRONMENT)
    return app
