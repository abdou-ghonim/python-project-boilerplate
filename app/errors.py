"""JSON error handlers.

An API that answers a bad request with Flask's HTML error page breaks every
client that assumed JSON, and in production the debug traceback is an
information leak. Registered for the whole app; the SPA catch-all in
app/routes.py still serves HTML for browser navigation.
"""
from __future__ import annotations

import logging

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from app.logging_setup import get_request_id

logger = logging.getLogger(__name__)


def _payload(message: str, status: int, **extra) -> tuple:
    body = {"error": message, "status": status, "request_id": get_request_id()}
    body.update(extra)
    return jsonify(body), status


def register_error_handlers(app: Flask) -> None:
    from app.auth import AuthError, TokenError

    @app.errorhandler(AuthError)
    def _auth_error(exc: AuthError):
        # Raised from inside auth routes, where returning a tuple from a nested
        # helper would mean threading the status back by hand.
        return _payload(exc.message, exc.status)

    @app.errorhandler(TokenError)
    def _token_error(exc: TokenError):
        return _payload(str(exc), 401)

    @app.errorhandler(ValueError)
    def _value_error(exc: ValueError):
        # Service-layer validation raises ValueError; a 400 with the message is
        # more useful to the caller than a 500 with none.
        if not request.path.startswith("/api/"):
            raise exc
        return _payload(str(exc), 400)

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        # Only the API speaks JSON; a browser hitting a bad URL should still get
        # the SPA shell or Flask's page.
        if not request.path.startswith("/api/"):
            return exc
        return _payload(exc.description or exc.name, exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        # Logged with the traceback, answered without it: the request id is the
        # thread connecting the two.
        logger.exception("Unhandled error on %s %s", request.method, request.path)
        if not request.path.startswith("/api/"):
            raise exc
        return _payload("Internal server error", 500)
