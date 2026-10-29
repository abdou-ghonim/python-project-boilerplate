"""Logging setup, and the request id that ties a log file together.

Called once from create_app() before anything else, so that a failing startup
check is itself logged. Handlers are attached to the root logger, which means
every `logging.getLogger(__name__)` in the codebase — plus SQLAlchemy, Werkzeug
and RQ — lands in the same place with no further wiring.

The request id lives here rather than in a file of its own because it exists for
the log: one id per request, generated on arrival (or taken from the inbound
header when a proxy already assigned one), attached to every record emitted
while handling it, and echoed back in the response. Without it, reading a log
from a multi-worker deployment means guessing which interleaved lines belong
together.
"""
from __future__ import annotations

import json
import logging
import logging.config
import uuid
from contextvars import ContextVar
from pathlib import Path

import config

# A ContextVar rather than flask.g: logging also happens in RQ workers and CLI
# commands, where no request context exists.
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(value: str | None = None) -> str:
    """Bind an id to the current context, generating one when not supplied."""
    rid = value or uuid.uuid4().hex[:16]
    _request_id.set(rid)
    return rid


def get_request_id() -> str:
    return _request_id.get()


def clear_request_id() -> None:
    _request_id.set("-")


class RequestIdFilter(logging.Filter):
    """Puts `request_id` on every record so formatters can reference it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


TEXT_FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log shippers that parse structured output.

    Hand-rolled rather than pulling in python-json-logger: the whole requirement
    is six fields and an exception, and a dependency that reads the log file's
    format is a dependency in every deployment.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Anything passed via logger.info(..., extra={...}) rides along.
        for key, value in getattr(record, "__dict__", {}).items():
            if key.startswith("ctx_"):
                payload[key[4:]] = value
        return json.dumps(payload, default=str)


def _handler(name: str, filename: Path, level: str) -> dict:
    return {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(filename),
        "maxBytes": config.LOG_MAX_BYTES,
        "backupCount": config.LOG_BACKUP_COUNT,
        "encoding": "utf-8",
        "formatter": "default",
        "filters": ["request_id"],
        "level": level,
    }


def configure_logging() -> None:
    """Install the application's logging configuration. Idempotent."""
    handlers: dict[str, dict] = {}
    active: list[str] = []

    if config.LOG_TO_CONSOLE:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "default",
            "filters": ["request_id"],
            "level": config.LOG_LEVEL,
        }
        active.append("console")

    if config.LOG_TO_FILE:
        # Created here rather than committed as an empty directory: a container
        # with LOG_DIR pointed at a mounted volume has nothing to commit.
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers["file"] = _handler("file", config.LOG_DIR / "app.log", config.LOG_LEVEL)
        # A separate error log so "did anything break today?" is one `wc -l`
        # rather than a grep through everything the app logged.
        handlers["error_file"] = _handler("error", config.LOG_DIR / "error.log", "ERROR")
        active += ["file", "error_file"]

    formatter = ({"()": f"{__name__}.JsonFormatter"} if config.LOG_FORMAT == "json"
                 else {"format": TEXT_FORMAT})

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_id": {"()": RequestIdFilter}},
        "formatters": {"default": formatter},
        "handlers": handlers,
        "root": {"level": config.LOG_LEVEL, "handlers": active},
        "loggers": {
            # Werkzeug's per-request line duplicates the access log gunicorn
            # already writes; keep it for warnings only.
            "werkzeug": {"level": "WARNING", "propagate": True},
            # DB_ECHO=true is the supported way to see SQL; the engine logger
            # would otherwise emit every statement at INFO.
            "sqlalchemy.engine": {"level": "WARNING", "propagate": True},
        },
    })

    logging.getLogger(__name__).debug(
        "Logging configured: level=%s format=%s dir=%s",
        config.LOG_LEVEL, config.LOG_FORMAT, config.LOG_DIR if config.LOG_TO_FILE else "-",
    )
