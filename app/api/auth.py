"""/api/auth — thin shell around the configured auth provider.

The shared endpoints live here; everything provider-specific (how a login is
actually performed) is attached by the provider itself in register_routes().

The blueprint is built per application rather than at import time: a provider
adds its routes when the app is created, and a module-level blueprint would be
written to twice as soon as a second app exists — which is every test run, and
anything that creates an app inside a worker.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

import config
from app.auth import get_auth_provider


def build_blueprint() -> Blueprint:
    bp = Blueprint("auth", __name__, url_prefix="/api/auth")
    provider = get_auth_provider()

    @bp.get("/config")
    def auth_config():
        """Tells the SPA which provider is live, so one Login page serves all three.

        Deliberately unauthenticated and deliberately free of secrets: it carries
        the provider name, the login style and, for OIDC, the URL to redirect to.
        """
        return jsonify({
            **provider.public_config(),
            "app_name": config.APP_NAME,
            "version": config.APP_VERSION,
        })

    provider.register_routes(bp)
    return bp


def register(app):
    app.register_blueprint(build_blueprint())
