"""API blueprints.

register_api() is the single place a new module is wired in; a blueprint with a
`bp` attribute needs one line in MODULES and nothing else.
"""
from __future__ import annotations

import logging
from importlib import import_module

from flask import Flask

logger = logging.getLogger(__name__)

#: Modules under app.api that expose either `bp` (a Blueprint) or `register(app)`.
MODULES = ("auth", "items")


def register_api(app: Flask) -> None:
    for name in MODULES:
        module = import_module(f"{__name__}.{name}")
        if hasattr(module, "register"):
            module.register(app)            # provider-driven routes (auth)
        else:
            app.register_blueprint(module.bp)
        logger.debug("Registered API module %s", name)
