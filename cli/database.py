"""Database commands: applying the schema, reflecting it, connectivity.

The order these run in is the shape of the project — SQL first, models second:

    flask db-apply          sql/<provider>/*.sql  ->  database
    flask generate-models   database              ->  app/models/models.py
"""
from __future__ import annotations

import sys
from contextlib import ExitStack
from pathlib import Path

import click
from flask.cli import with_appcontext
from sqlalchemy import MetaData, Table, create_engine, inspect

import config
from app.extensions import db
from app import database
from app.sql_scripts import (SchemaScriptsNotFound, apply_scripts, script_dir,
                             script_paths, split_statements)

_NO_GENERATED_MODELS = """\
app/models/models.py holds no models, so there is nothing to create.

This project is database first — the schema is SQL, and the models are derived
from it:

    flask db-apply          apply sql/{dialect}/*.sql to the database
    flask generate-models   reflect that database into app/models/models.py

db-init is the trip back the other way, for standing an already-reflected
schema up in an empty database. It only makes sense once models.py exists."""


@click.command(name="db-apply")
@click.option("--dialect", "dialect_name", default=None,
              help="Which sql/<dialect>/ directory to run. Default: DB_PROVIDER.")
@click.option("--dir", "directory", default=None,
              help=f"Where the dialect directories live. Default: {config.SQL_SCHEMA_DIR}")
@click.option("--dry-run", is_flag=True, help="List the scripts and statement counts.")
@click.option("--no-seed", is_flag=True, help="Skip creating the default admin.")
@with_appcontext
def db_apply(dialect_name: str | None, directory: str | None, dry_run: bool,
             no_seed: bool) -> None:
    """Apply sql/<dialect>/*.sql to the configured database, in filename order.

    Scripts are written to be safe to re-run, so this is the normal way to bring
    a database up to date as well as the way to create it. It keeps no record of
    what has already run: for versioning and rollback across environments, reach
    for a migration tool instead.
    """
    database.ensure_driver()
    target = dialect_name or database.dialect().name

    try:
        paths = script_paths(target, directory)
    except SchemaScriptsNotFound as exc:
        raise click.ClickException(str(exc)) from exc
    if not paths:
        raise click.ClickException(
            f"No .sql files in {script_dir(target, directory)}.")

    click.echo(f"Applying {len(paths)} script(s) from "
               f"{script_dir(target, directory)}")

    if dry_run:
        for path in paths:
            count = len(split_statements(path.read_text(encoding="utf-8")))
            click.echo(f"  {path.name:<40}{count} statement(s)")
        click.secho("Dry run — nothing was executed.", fg="yellow")
        return

    try:
        applied = apply_scripts(db.engine, paths)
    except Exception as exc:                                    # noqa: BLE001
        # The file name matters more than the traceback: it is the thing the
        # person running this has to open and fix.
        raise click.ClickException(f"Failed while applying the schema — {exc}") from exc

    for path, count in applied:
        click.secho(f"  {path.name:<40}{count} statement(s)", fg="green")

    if not no_seed:
        from cli.users import seed_default_admin
        seed_default_admin()


@click.command(name="db-init")
@click.option("--drop", is_flag=True, help="Drop every table first. Destroys all data.")
@with_appcontext
def db_init(drop: bool) -> None:
    """Create tables from the Python models. Needs app/models/models.py first.

    The code-first direction, kept for the one case that wants it: standing an
    already-reflected schema up in an empty database (a test instance, a CI
    service container). Everywhere else the schema comes from sql/ — see
    `flask db-apply`.

    What it creates is whatever SQLAlchemy was told about, which is close to but
    not the same thing as what the SQL scripts say; treat sql/ as the authority
    when the two disagree.
    """
    names, metadatas = _generated_models()
    if not names:
        raise click.ClickException(
            _NO_GENERATED_MODELS.format(dialect=database.dialect().name))

    click.echo(f"{len(names)} model(s) in {config.MODELS_OUTFILE}")

    if drop:
        if not click.confirm("This deletes every row in every table. Continue?"):
            raise click.Abort
        for metadata in metadatas:
            metadata.drop_all(db.engine)
        db.drop_all()
        click.echo("Dropped all tables.")

    for metadata in metadatas:
        metadata.create_all(db.engine)
    # The application's own tables (app_user, item) are mapped by hand in
    # extended_models.py and live on a different metadata to the generated ones.
    db.create_all()
    click.echo(f"Tables created on {config.DB_PROVIDER}.")

    from cli.users import seed_default_admin
    seed_default_admin()


@click.command(name="db-check")
@with_appcontext
def db_check() -> None:
    """Report what the app is connected to, and whether it answers."""
    # Credentials are masked: this command's output ends up in tickets and
    # terminal scrollback more often than anyone intends.
    uri = database.uri()
    if "@" in uri:
        scheme, _, rest = uri.partition("://")
        uri = f"{scheme}://***@{rest.split('@', 1)[1]}"

    click.echo(f"Provider : {database.dialect().name}")
    click.echo(f"URI      : {uri}")
    reachable = False
    try:
        db.session.execute(db.text("SELECT 1"))
        click.secho("Database : reachable", fg="green")
        reachable = True
    except Exception as exc:                                    # noqa: BLE001
        click.secho(f"Database : UNREACHABLE — {exc}", fg="red")

    if reachable:
        # Which of the app's own tables exist is the usual thing someone is
        # actually asking when they run this on a fresh environment.
        tables = set(inspect(db.engine).get_table_names())
        missing = sorted(set(db.metadata.tables) - tables)
        if missing:
            click.secho(f"Schema   : {len(tables)} table(s); missing "
                        f"{', '.join(missing)} — run `flask db-apply`", fg="yellow")
        else:
            click.secho(f"Schema   : {len(tables)} table(s)", fg="green")

    generated, _ = _generated_models()
    if generated:
        click.echo(f"Models   : {len(generated)} in {config.MODELS_OUTFILE}")
    else:
        click.echo(f"Models   : {config.MODELS_OUTFILE} is empty "
                   "— run `flask generate-models`")

    from app.redis import health
    status = health()
    if status.get("enabled") is False:
        click.echo("Redis    : off (REDIS_ENABLED=false)")
    elif status.get("connected"):
        click.secho(f"Redis    : reachable (v{status.get('version')})", fg="green")
    else:
        colour = "red" if status.get("required") else "yellow"
        click.secho(f"Redis    : unavailable ({status.get('error', 'not connected')})",
                    fg=colour)

    from app.auth import get_auth_provider
    click.echo(f"Auth     : {get_auth_provider().name}")


@click.command(name="generate-models")
@click.option("--outfile", default=None, help=f"Default: {config.MODELS_OUTFILE}")
@click.option("--schemas", default=None, help="Comma-separated; default: the provider's.")
@click.option("--noviews", is_flag=True, help="Skip views.")
@click.option("--include-owned", is_flag=True,
              help="Also emit tables this app already maps in extended_models.py.")
@click.option("--dry-run", is_flag=True, help="Write to stdout instead of the file.")
def generate_models(outfile: str | None, schemas: str | None, noviews: bool,
                    include_owned: bool, dry_run: bool) -> None:
    """Reflect the live database into app/models/models.py.

    Rewrites the file in full, which is why hand-written models belong in
    extended_models.py. The provider supplies the default schema list, so this
    works unchanged across SQL Server, PostgreSQL, MySQL and SQLite.
    """
    from lib import DeclarativeGenerator

    database.ensure_driver()
    target = Path(outfile or config.MODELS_OUTFILE)

    schema_list: list[str | None] = (
        [s.strip() for s in schemas.split(",") if s.strip()] if schemas
        else database.reflection_schemas())

    click.echo(f"Reflecting {database.dialect().name} schemas: "
               f"{', '.join(str(s) for s in schema_list)}")

    engine = create_engine(database.uri())
    metadata = MetaData()
    only = list(config.DATABASE_INCLUDE_TABLES) or None
    for schema in schema_list:
        metadata.reflect(engine, schema, not noviews, only=only)

    for table in config.DATABASE_EXCLUDE_TABLES:
        metadata.tables.pop(table, None)
    if config.IGNORE_AUDIT_TRAIL_TABLES:
        for name in [t for t in metadata.tables if t.endswith("_AuditTrail")]:
            metadata.remove(metadata.tables[name])

    if not include_owned:
        # app_user and item are mapped by hand in extended_models.py. Reflecting
        # them as well would put two mapped classes on one table and leave the
        # generated copy, which has none of the password handling, looking like
        # the real one.
        skipped = _drop_owned_tables(metadata)
        if skipped:
            click.echo(f"Skipping tables this app maps itself: {', '.join(skipped)} "
                       "(--include-owned to emit them anyway)")

    if not metadata.tables:
        click.secho("No tables reflected — check DATABASE_SCHEMAS and the connection.",
                    fg="yellow")
        return

    generator = DeclarativeGenerator(metadata, engine, set())
    code = generator.generate()

    with ExitStack() as stack:
        if dry_run:
            sys.stdout.write(code)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(target.open("w", encoding="utf-8"))
            handle.write(code)
            click.secho(f"Wrote {len(metadata.tables)} tables to {target}", fg="green")


def _drop_owned_tables(metadata: MetaData) -> list[str]:
    """Remove reflected tables that extended_models.py already maps."""
    from app import models                                      # noqa: F401

    owned = {table.name for table in db.metadata.tables.values()}
    removed = []
    for table in list(metadata.tables.values()):
        if table.name in owned:
            metadata.remove(table)
            removed.append(table.name)
    return sorted(removed)


def _generated_models() -> tuple[list[str], list[MetaData]]:
    """The classes and Tables in the generated models file, and their metadata.

    The generated file carries a declarative base of its own, separate from
    Flask-SQLAlchemy's, so its tables are invisible to `db.create_all()` and
    have to be collected by hand.
    """
    from app.models import models as generated

    names: list[str] = []
    metadatas: list[MetaData] = []
    for name, obj in vars(generated).items():
        if name.startswith("_"):
            continue
        table = None
        if isinstance(obj, Table):
            table = obj
        elif isinstance(obj, type) and getattr(obj, "__table__", None) is not None:
            table = obj.__table__
        if table is None:
            continue
        names.append(name)
        if not any(table.metadata is seen for seen in metadatas):
            metadatas.append(table.metadata)
    return sorted(names), metadatas
