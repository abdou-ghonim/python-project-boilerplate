"""Everything that differs between database backends, in one place.

Four dialects are supported — sqlite, postgresql, mysql, mssql — and the rest of
the application asks none of the questions they disagree on: how to build the
connection URI, how to tune the engine, whether the connection is encrypted, and
which schemas `flask generate-models` should reflect.

There is no provider object and no cache: every function reads `config` when it
is called, so a test that rebinds DB_* gets the new answer without resetting
anything.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus

import config

logger = logging.getLogger(__name__)


class DriverMissingError(RuntimeError):
    """The selected dialect's DBAPI driver is not installed.

    Carries the install command, because the alternative — a bare ImportError
    from deep inside SQLAlchemy — tells the reader nothing about which extra
    requirements file they were supposed to install.
    """


@dataclass(frozen=True)
class Dialect:
    """The static facts about a backend. The behaviour is below."""

    name: str
    #: SQLAlchemy URL prefix, driver included.
    url_prefix: str
    default_port: int | None = None
    #: Import name of the DBAPI driver, checked before the first connection.
    driver_module: str | None = None
    #: pip requirement that provides it, quoted in DriverMissingError.
    requirements_file: str | None = None
    #: Default schemas to reflect. None means "the connection's default schema".
    schemas: tuple[str | None, ...] = (None,)
    #: Lowercased URI substrings that prove the connection is encrypted.
    encrypted_when: tuple[str, ...] = ()
    #: What to tell someone whose connection turns out not to be.
    tls_remedy: str = ""
    #: Extra SQLAlchemy engine kwargs for this backend.
    engine_extra: dict = field(default_factory=dict)


DIALECTS: dict[str, Dialect] = {
    "sqlite": Dialect(
        name="sqlite",
        url_prefix="sqlite",
        # SQLite uses SingletonThreadPool/NullPool depending on the URL, and
        # passing pool_size to either is a TypeError — so the shared pooling
        # defaults below are skipped for it entirely. check_same_thread is off
        # because Flask serves requests on several threads.
        engine_extra={"connect_args": {"check_same_thread": False}},
    ),
    "postgresql": Dialect(
        name="postgresql",
        url_prefix="postgresql+psycopg",
        default_port=5432,
        driver_module="psycopg",
        requirements_file="requirements/postgresql.txt",
        schemas=("public",),
        encrypted_when=("sslmode=require", "sslmode=verify-ca", "sslmode=verify-full"),
        tls_remedy="libpq defaults to sslmode=prefer, which falls back to plaintext "
                   "without telling anyone. Append sslmode=require (or verify-full).",
    ),
    "mysql": Dialect(
        name="mysql",
        url_prefix="mysql+pymysql",
        default_port=3306,
        driver_module="pymysql",
        requirements_file="requirements/mysql.txt",
        # MySQL has no schema layer below the database: the database *is* the
        # schema. schemas=() means "whatever DB_NAME says", resolved below.
        schemas=(),
        encrypted_when=("ssl_verify_cert=true", "ssl_verify_identity=true",
                        "ssl_ca=", "ssl=true"),
        tls_remedy="PyMySQL only negotiates TLS when an ssl_* parameter is present. "
                   "Add ssl_verify_cert=true, or ssl_ca=/path/to/ca.pem.",
    ),
    "mssql": Dialect(
        name="mssql",
        url_prefix="mssql+pyodbc",
        default_port=1433,
        driver_module="pyodbc",
        requirements_file="requirements/mssql.txt",
        schemas=("dbo",),
        encrypted_when=("encrypt=yes", "encrypt=true"),
        tls_remedy="ODBC Driver 17 defaults to Encrypt=no. Append Encrypt=yes.",
        # Turns executemany() into a single batched round trip. Without it a bulk
        # insert is one network round trip per row, which is the difference
        # between seconds and minutes on a seed or an import.
        engine_extra={"fast_executemany": True},
    ),
}

#: Spellings people reasonably reach for, mapped to the canonical name.
ALIASES = {
    "postgres": "postgresql", "psql": "postgresql", "pg": "postgresql",
    "mariadb": "mysql", "sqlserver": "mssql", "sql-server": "mssql",
    "mssqlserver": "mssql",
}


def dialect(name: str | None = None) -> Dialect:
    """The configured dialect, or the one explicitly named."""
    key = (name or config.DB_PROVIDER).strip().lower()
    key = ALIASES.get(key, key)
    if key not in DIALECTS:
        raise RuntimeError(
            f"DB_PROVIDER={key!r} is not a known database. "
            f"Choose one of: {', '.join(sorted(DIALECTS))}.")
    return DIALECTS[key]


def uri() -> str:
    """The SQLAlchemy URI, built from DB_* or taken from the override.

    SQLALCHEMY_DATABASE_URI wins so that a managed-database connection string
    (which rarely decomposes into host/port/name) can be pasted in whole.
    """
    if config.DATABASE_URI_OVERRIDE:
        return config.DATABASE_URI_OVERRIDE

    current = dialect()
    if current.name == "sqlite":
        if config.DB_PATH in (":memory:", "memory"):
            return "sqlite:///:memory:"
        path = Path(config.DB_PATH)
        if not path.is_absolute():
            path = config.BASE_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"

    return (f"{current.url_prefix}://{_credentials()}"
            f"{config.DB_HOST}{_port(current)}/{config.DB_NAME}{_query(current)}")


def engine_options() -> dict:
    """SQLAlchemy engine kwargs. The pooling defaults suit a web worker."""
    current = dialect()
    options: dict = {"echo": config.DB_ECHO, **current.engine_extra}
    if current.name != "sqlite":
        options.update({
            # A connection the server recycled is otherwise discovered as a
            # failed query, on someone's request.
            "pool_pre_ping": True,
            "pool_size": config.DB_POOL_SIZE,
            "max_overflow": config.DB_MAX_OVERFLOW,
            # MySQL in particular closes idle connections at wait_timeout, far
            # below 8h on managed instances; recycling below it turns "server has
            # gone away" into a no-op reconnect.
            "pool_recycle": config.DB_POOL_RECYCLE,
        })
    return options


def ensure_driver() -> None:
    """Fail early, and legibly, when the DBAPI driver is not installed."""
    current = dialect()
    if not current.driver_module:
        return
    try:
        __import__(current.driver_module)
    except ImportError as exc:
        raise DriverMissingError(
            f"DB_PROVIDER={current.name} needs the {current.driver_module!r} driver, "
            f"which is not installed. Run: pip install -r {current.requirements_file}"
        ) from exc


def check_transport_security(connection_uri: str, *, development: bool) -> None:
    """Refuse an unencrypted connection outside development.

    Default-off encryption is the norm across these drivers, and the failure mode
    is invisible: the app works perfectly while every query and every row it
    returns crosses the network in the clear.
    """
    current = dialect()
    lowered = connection_uri.lower()

    if current.name == "sqlite":
        # A local file has no transport to encrypt. It is still the wrong choice
        # for a deployment: concurrent writers serialise on a single lock and the
        # data lives inside the container's writable layer.
        if not development:
            logger.warning(
                "DB_PROVIDER=sqlite outside a development environment. SQLite has no "
                "network transport to secure, but it also has no concurrent writes "
                "and no durability guarantee across container restarts.")
        return

    if not any(marker in lowered for marker in current.encrypted_when) \
            and config.DB_REQUIRE_TLS:
        message = (f"The {current.name} connection is not encrypted. "
                   f"{current.tls_remedy} "
                   "Set DB_REQUIRE_TLS=false to accept this deliberately.")
        if not development:
            raise RuntimeError(message)
        logger.warning("%s Acceptable in development only.", message)

    if current.name == "mssql" and "trustservercertificate=yes" in lowered \
            and not development:
        logger.warning(
            "The database connection sets TrustServerCertificate=yes: traffic is "
            "encrypted but the server certificate is not validated, so it is not "
            "protected against an active attacker. Prefer a trusted certificate "
            "and DB_VERIFY_CERT=true.")


def reflection_schemas() -> list[str | None]:
    """Schemas `flask generate-models` reflects when DATABASE_SCHEMAS is unset."""
    if config.DATABASE_SCHEMAS:
        return list(config.DATABASE_SCHEMAS)
    current = dialect()
    if current.name == "mysql":
        return [config.DB_NAME]
    return list(current.schemas)


def _query(current: Dialect) -> str:
    """The dialect's TLS parameters, joined with the operator's DB_OPTIONS."""
    params: dict[str, str] = {}
    if current.name == "postgresql":
        # libpq's own default is sslmode=prefer: it tries TLS and silently falls
        # back to plaintext when the server declines, which is indistinguishable
        # from success. Ask for the strict mode when we require encryption.
        if config.DB_REQUIRE_TLS:
            params["sslmode"] = "verify-full" if config.DB_VERIFY_CERT else "require"
        else:
            params["sslmode"] = "prefer"
    elif current.name == "mysql":
        params["charset"] = "utf8mb4"
        if config.DB_REQUIRE_TLS:
            # PyMySQL enables TLS as soon as any ssl_* parameter is present.
            verify = "true" if config.DB_VERIFY_CERT else "false"
            params["ssl_verify_cert"] = verify
            params["ssl_verify_identity"] = verify
    elif current.name == "mssql":
        params["driver"] = config.DB_ODBC_DRIVER
        params["Encrypt"] = "yes" if config.DB_REQUIRE_TLS else "no"
        params["TrustServerCertificate"] = "no" if config.DB_VERIFY_CERT else "yes"

    parts = [f"{k}={quote_plus(str(v))}" for k, v in params.items() if v != ""]
    if config.DB_OPTIONS:
        parts.append(config.DB_OPTIONS.lstrip("?&"))
    return f"?{'&'.join(parts)}" if parts else ""


def _credentials() -> str:
    """`user:password@` for the URI, percent-encoded, or '' when anonymous.

    Passwords routinely contain @ / : and #; leaving them unencoded produces a
    URI that parses into the wrong host and a connection error that blames the
    network rather than the punctuation.
    """
    if not config.DB_USER:
        return ""
    user = quote_plus(config.DB_USER)
    if not config.DB_PASSWORD:
        return f"{user}@"
    return f"{user}:{quote_plus(config.DB_PASSWORD)}@"


def _port(current: Dialect) -> str:
    port = config.DB_PORT or current.default_port
    return f":{port}" if port else ""
