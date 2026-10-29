"""Cache and demo-data commands.

No `routes` command: Flask ships one, and its CLI group resolves the name
before the application's own, so a custom one here could never run.
"""
from __future__ import annotations

import click
from flask.cli import with_appcontext


@click.command(name="cache-clear")
@click.argument("namespace", default="")
@with_appcontext
def cache_clear(namespace: str) -> None:
    """Drop a cache namespace, or every namespace when none is given."""
    from app.redis import cache_invalidate

    removed = cache_invalidate(namespace or "*")
    click.secho(f"Removed {removed} cached key(s).", fg="green")


@click.command(name="seed-demo")
@click.option("--count", default=25, show_default=True)
@with_appcontext
def seed_demo(count: int) -> None:
    """Insert sample items so the demo page has something to show."""
    import random

    from app.models import Item, db

    statuses = ("active", "pending", "archived")
    for index in range(count):
        db.session.add(Item(
            name=f"Sample item {index + 1}",
            description="Created by `flask seed-demo`.",
            status=random.choice(statuses),
            quantity=random.randint(0, 500),
        ))
    db.session.commit()

    from app.redis import cache_invalidate
    from app.services.item_service import CACHE_NAMESPACE
    cache_invalidate(CACHE_NAMESPACE)
    click.secho(f"Inserted {count} items.", fg="green")
