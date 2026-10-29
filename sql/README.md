# Schema

This project is **database first**. The schema lives here, in SQL, and the
Python models are derived from it — not the other way round.

```
sql/<dialect>/NNN_name.sql      applied in filename order by `flask db-apply`
```

One directory per `DB_PROVIDER`: `sqlite`, `postgresql`, `mysql`, `mssql`.
`001_core.sql` holds the two tables the boilerplate ships with — `app_user`,
which the auth providers read, and `item`, the demo table behind `/api/items`.

## The round trip

```bash
flask db-apply          # SQL  ->  database
flask generate-models   # database -> app/models/models.py
```

`generate-models` reflects the live database through `lib/sql_code_generate`
and rewrites `app/models/models.py` in full, so nothing hand-written survives
there; hand-written models and the methods hung off them live in
`app/models/extended_models.py`.

Tables this application already maps itself are skipped by `generate-models`,
which is why `app_user` and `item` do not appear twice. `--include-owned`
turns that off.

## Writing a change

Add a file rather than editing one that has already been applied somewhere:

```
sql/postgresql/002_add_item_owner.sql
```

Every statement should be safe to re-run — `CREATE TABLE IF NOT EXISTS`,
`IF NOT EXISTS (SELECT 1 FROM sys.indexes …)`, and so on. `db-apply` keeps no
ledger of what it has run, so re-running the directory is the normal case and
has to be a no-op. If you need ordering guarantees, versioning and rollback
across many environments, that is a migration tool's job (Alembic, Flyway,
`sqlpackage`); this is deliberately the smaller thing.

Keep the dialects in step. `tests/test_schema_sql.py` checks the SQLite file
against the ORM models, which catches a column added to one and forgotten in
the other — but only for SQLite, so the remaining three are on you.

## Verifying a dialect

SQLite is the only one the test suite covers, because it is the only one that
needs no server. The other three are checked by hand against the database
containers already in `docker-compose.yml` — worth doing whenever one of their
files changes, and **not yet done for the files in this repository**.

```bash
pip install -r requirements/postgresql.txt
docker compose --profile postgresql up -d db-postgresql

export FLASK_APP=run.py DB_PROVIDER=postgresql
export DB_HOST=localhost DB_NAME=app DB_USER=app DB_PASSWORD=app
export DB_REQUIRE_TLS=false      # a container on localhost, not a network hop

flask db-apply                   # applies cleanly
flask db-apply                   # and is a no-op the second time
flask db-check                   # Schema : 2 table(s), none missing
flask generate-models --include-owned --dry-run
```

That last line is the real check. It reflects what the DDL actually built, so a
column that came out nullable when the model says otherwise, a default that did
not stick, or an index that was never created shows up as a difference against
`app/models/extended_models.py`. `flask db-apply && flask seed-demo` and a
login prove the rest.

MySQL is the same with `--profile mysql`, `db-mysql` and
`requirements/mysql.txt`.

SQL Server needs `requirements/mssql.txt` and the Microsoft ODBC 18 driver on
the host, logs in as `sa`, and starts with no application database, so create
one first:

```bash
docker compose --profile mssql up -d db-mssql
export DB_PROVIDER=mssql DB_USER=sa DB_PASSWORD='Str0ng!Passw0rd'
export DB_VERIFY_CERT=false      # the image ships a self-signed certificate

docker compose exec db-mssql /opt/mssql-tools18/bin/sqlcmd \
    -S localhost -U sa -P "$DB_PASSWORD" -C -Q "CREATE DATABASE app"
```

It is the dialect most likely to break, because it is the only one whose file
depends on `GO` batching rather than semicolons.

## Statement separation

Statements end with `;` at the end of a line. Semicolons inside strings,
`--` comments and `/* … */` comments are ignored by the splitter. Where a
statement contains semicolons of its own — T-SQL `BEGIN … END`, triggers,
stored procedures — separate batches with a line containing only `GO`, as the
SQL Server file does.
