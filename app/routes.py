"""Non-API routes: health, and the SPA.

Everything that is not /api/* and not a real file in the build output is served
the SPA shell, because client-side routing means /items is a React route rather
than a path on disk.
"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, current_app, jsonify, send_from_directory

import config
from app.extensions import db
from app.redis import health as redis_health
from app.logging_setup import get_request_id

logger = logging.getLogger(__name__)

main = Blueprint("main", __name__)


@main.get("/health")
def health():
    """Liveness and dependency check, used by Docker's HEALTHCHECK.

    Answers 200 only when the database answers: a container that cannot reach
    its database is not healthy, however well Flask itself is running.
    """
    checks = {"database": {"connected": False}, "redis": redis_health()}
    status = 200
    try:
        db.session.execute(db.text("SELECT 1"))
        checks["database"] = {"connected": True, "provider": config.DB_PROVIDER}
    except Exception as exc:                                    # noqa: BLE001
        logger.error("Health check: database unreachable: %s", exc)
        checks["database"] = {"connected": False, "provider": config.DB_PROVIDER,
                              "error": str(exc)}
        status = 503

    if config.REDIS_REQUIRED and not checks["redis"].get("connected"):
        status = 503

    return jsonify({
        "status": "ok" if status == 200 else "degraded",
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "environment": config.ENVIRONMENT,
        "checks": checks,
    }), status


@main.get("/", defaults={"path": ""})
@main.get("/<path:path>")
def spa(path: str):
    """Serve the built SPA, falling back to index.html for client routes."""
    # An unmatched /api/* path belongs to the API, not to client-side routing:
    # serving it the SPA shell would answer a mistyped endpoint with HTML (or,
    # before a build exists, with a confusing "frontend not found").
    if path.startswith("api/"):
        return jsonify({"error": "Not found", "status": 404,
                        "request_id": get_request_id()}), 404

    static_folder = Path(current_app.static_folder or "")
    candidate = static_folder / path
    if path and candidate.is_file():
        return send_from_directory(static_folder, path)

    index = static_folder / "index.html"
    if not index.is_file():
        # The usual cause is running the API without having built the frontend;
        # say so rather than answering a bare 404.
        return jsonify({
            "error": "Frontend build not found.",
            "detail": f"Expected {index}. Run `npm run build` in frontend/, or use "
                      "the Vite dev server on port 5173 during development.",
            "status": 404,
        }), 404
    return send_from_directory(static_folder, "index.html")
