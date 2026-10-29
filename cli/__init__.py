"""Command-line interface.

Every command is registered on `app.cli`, so they run as `flask <name>` with an
application context already in place — the same configuration, the same database
provider and the same logging as the web process.

    flask db-check                  what am I connected to?
    flask db-apply                  run sql/<provider>/*.sql, seed the admin
    flask generate-models           reflect the database into app/models/models.py
    flask db-init                   code-first fallback; needs models.py first
    flask create-user               add a local account
    flask seed-demo                 sample data for the demo page
    flask jobs worker               run the background worker
"""
from __future__ import annotations

from flask import Flask

from .database import db_apply, db_check, db_init, generate_models
from .jobs import jobs
from .maintenance import cache_clear, seed_demo
from .users import create_admin, create_user, list_users, set_role

COMMANDS = (
    db_apply, db_check, generate_models, db_init,
    create_admin, create_user, list_users, set_role,
    cache_clear, seed_demo,
    jobs,
)


def register_commands(app: Flask) -> None:
    for command in COMMANDS:
        app.cli.add_command(command)


__all__ = ["register_commands", "COMMANDS"]
