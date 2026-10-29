"""Single source of configuration, read from the environment (.env in development).

Everything the app can be tuned with lives here as a module-level constant, so a
reader can answer "what is configurable?" by reading one file. Values that decide
whether the app is *safe* to run — the signing key, the database transport, the
auth provider — are validated at startup in app/__init__.py rather than here, so
that a bad value is a boot failure with an actionable message instead of a
surprise at the first request.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def _flag(name: str, default: str = "false") -> bool:
    """Read a boolean env var. Accepts 1/true/yes/on in any case."""
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw else default


def _mapping(name: str) -> dict[str, str]:
    """Read "a=b,c=d" into a dict. An empty value is kept — it means something."""
    out: dict[str, str] = {}
    for pair in (os.getenv(name) or "").split(","):
        attribute, sep, column = pair.partition("=")
        if sep and attribute.strip():
            out[attribute.strip()] = column.strip()
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Application identity
# ─────────────────────────────────────────────────────────────────────────────
APP_NAME = os.getenv("APP_NAME", "Python Project Boilerplate")
APP_SLUG = os.getenv("APP_SLUG", "boilerplate")
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")
BASE_URL = os.getenv("BASE_URL", "http://localhost:5000/")
TIMEZONE = os.getenv("TIMEZONE", "Australia/Sydney")

# Deployment environment marker. An unset value is treated as production: every
# development-only affordance in this codebase asks `is_development()` first, so
# the fail-closed default matters more than the convenience.
ENVIRONMENT = os.getenv("FLASK_ENV", "production").strip().lower()
DEV_ENVIRONMENT_NAMES = ("development", "dev", "local", "test")


def is_development(testing: bool = False) -> bool:
    """True when this process is explicitly running in a development environment."""
    return testing or ENVIRONMENT in DEV_ENVIRONMENT_NAMES


# ─────────────────────────────────────────────────────────────────────────────
# Secrets
# ─────────────────────────────────────────────────────────────────────────────
# The placeholder the app must never run with. create_app() refuses to boot when
# SECRET_KEY is unset, equal to this, or shorter than 32 bytes — a guessable
# signing key lets anyone forge a JWT, including one claiming role=admin.
INSECURE_SECRET_KEY = "change-me-in-production"
SECRET_KEY = os.getenv("SECRET_KEY", INSECURE_SECRET_KEY)

# ─────────────────────────────────────────────────────────────────────────────
# Database  (app/database.py)
# ─────────────────────────────────────────────────────────────────────────────
# Which provider builds the connection URI and owns the dialect-specific
# behaviour: sqlite | postgresql | mysql | mssql.
DB_PROVIDER = os.getenv("DB_PROVIDER", "sqlite").strip().lower()

# Discrete connection parts. The provider assembles them, so switching backends
# is a one-line change rather than a rewritten URI.
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = _int("DB_PORT", 0) or None          # None → the provider's default port
DB_NAME = os.getenv("DB_NAME", "app")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
# sqlite only: file path, relative to BASE_DIR unless absolute.
DB_PATH = os.getenv("DB_PATH", "app.db")
# Extra query parameters appended verbatim, e.g. "charset=utf8mb4&connect_timeout=5".
DB_OPTIONS = os.getenv("DB_OPTIONS", "")
# mssql only: the ODBC driver name registered with unixODBC.
DB_ODBC_DRIVER = os.getenv("DB_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
# Require an encrypted connection. Enforced by the provider's transport check,
# which is fatal outside development — an unencrypted link puts every query and
# every row of PII on the wire in the clear, and nothing surfaces that at runtime.
DB_REQUIRE_TLS = _flag("DB_REQUIRE_TLS", "true")
# Validate the server certificate. Turning this off keeps the traffic encrypted
# but offers no protection against an active attacker.
DB_VERIFY_CERT = _flag("DB_VERIFY_CERT", "true")

# Escape hatch: a complete SQLAlchemy URI, used verbatim when set. Useful for
# managed-database connection strings that do not decompose into the parts above.
DATABASE_URI_OVERRIDE = os.getenv("SQLALCHEMY_DATABASE_URI", "")

# Connection pool (ignored by sqlite).
DB_POOL_SIZE = _int("DB_POOL_SIZE", 5)
DB_MAX_OVERFLOW = _int("DB_MAX_OVERFLOW", 10)
DB_POOL_RECYCLE = _int("DB_POOL_RECYCLE", 280)
DB_ECHO = _flag("DB_ECHO")

# Database first: the schema is written as SQL under sql/<provider>/, applied by
# `flask db-apply`, and reflected back into MODELS_OUTFILE by
# `flask generate-models`. Nothing creates tables from the Python models.
SQL_SCHEMA_DIR = os.getenv("SQL_SCHEMA_DIR", "sql")

# Reflection scope for `flask generate-models`. Empty → the provider's default
# schema for the active backend.
DATABASE_SCHEMAS = [s for s in os.getenv("DATABASE_SCHEMAS", "").split(",") if s.strip()]
DATABASE_INCLUDE_TABLES = [t for t in os.getenv("DATABASE_INCLUDE_TABLES", "").split(",") if t.strip()]
DATABASE_EXCLUDE_TABLES = [t for t in os.getenv("DATABASE_EXCLUDE_TABLES", "").split(",") if t.strip()]
IGNORE_AUDIT_TRAIL_TABLES = _flag("IGNORE_AUDIT_TRAIL_TABLES", "true")
MODELS_OUTFILE = os.getenv("MODELS_OUTFILE", "app/models/models.py")

# ─────────────────────────────────────────────────────────────────────────────
# Authentication  (app/auth)
# ─────────────────────────────────────────────────────────────────────────────
# local → username/password against the User table
# oidc  → OpenID Connect against an external IdP (Entra ID, Google, Keycloak, Okta)
# none  → no authentication at all; refuses to load outside development
AUTH_PROVIDER = os.getenv("AUTH_PROVIDER", "local").strip().lower()

# The account `flask db-apply` / `flask create-admin` creates so a fresh install
# can be logged into. Seeding is refused outside development unless
# DEFAULT_ADMIN_PASSWORD is set to something other than the placeholder below —
# a known default admin password is a backdoor, not a convenience.
# The account table. Database first means it may already exist under a name of
# its own, with columns of its own: AUTH_USER_TABLE and AUTH_USER_SCHEMA point
# the model at it, and AUTH_USER_COLUMNS renames individual fields —
# "username=Email,display_name=FullName". An entry with nothing after the `=`
# says the table has no such column at all, and the model falls back to a
# constant for it ("role=" means everyone gets AUTH_DEFAULT_ROLE).
AUTH_USER_TABLE = os.getenv("AUTH_USER_TABLE", "app_user")
AUTH_USER_SCHEMA = os.getenv("AUTH_USER_SCHEMA", "").strip()
AUTH_USER_COLUMNS = _mapping("AUTH_USER_COLUMNS")

# Roles understood by @require_role, least privileged first. The order is the
# ranking: require_role("manager") also admits everything to its right.
ROLES = tuple(r.strip().lower() for r in
              os.getenv("AUTH_ROLES", "user,manager,admin").split(",") if r.strip())
AUTH_DEFAULT_ROLE = os.getenv("AUTH_DEFAULT_ROLE", ROLES[0]).strip().lower()

INSECURE_ADMIN_PASSWORD = "change-me"
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin@example.com")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", INSECURE_ADMIN_PASSWORD)

# local provider: lockout after repeated failures, counted in Redis so the limit
# is shared across workers (see app/utils/rate_limit.py).
LOGIN_MAX_ATTEMPTS = _int("LOGIN_MAX_ATTEMPTS", 5)
LOGIN_LOCKOUT_SECONDS = _int("LOGIN_LOCKOUT_SECONDS", 900)
PASSWORD_MIN_LENGTH = _int("PASSWORD_MIN_LENGTH", 12)

# oidc provider.
OIDC_DISCOVERY_URL = os.getenv("OIDC_DISCOVERY_URL", "")
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_SCOPES = os.getenv("OIDC_SCOPES", "openid email profile")
# Claim carrying the user's role(s). Azure AD uses "roles"; Keycloak nests them.
OIDC_ROLE_CLAIM = os.getenv("OIDC_ROLE_CLAIM", "roles")
OIDC_DEFAULT_ROLE = os.getenv("OIDC_DEFAULT_ROLE", "user")
# Where the SPA should land after a successful callback.
OIDC_POST_LOGIN_REDIRECT = os.getenv("OIDC_POST_LOGIN_REDIRECT", "/")
OIDC_STATE_TTL_SECONDS = _int("OIDC_STATE_TTL_SECONDS", 300)

# ─────────────────────────────────────────────────────────────────────────────
# JWT  (issued identically by every auth provider)
# ─────────────────────────────────────────────────────────────────────────────
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY_MINUTES = _int("JWT_EXPIRY_MINUTES", 60)
JWT_ISSUER = os.getenv("JWT_ISSUER", APP_SLUG)
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", f"{APP_SLUG}-api")
JWT_LEEWAY_SECONDS = _int("JWT_LEEWAY_SECONDS", 10)

# ─────────────────────────────────────────────────────────────────────────────
# Redis  (app/redis.py)
# ─────────────────────────────────────────────────────────────────────────────
# Off entirely: nothing connects, every Redis-backed feature becomes a no-op
# and app/redis.py can be deleted along with the four
# features below. See "Dropping what you do not need" in the README.
REDIS_ENABLED = _flag("REDIS_ENABLED", "true")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# Outside development an unreachable Redis is a boot failure: rate limiting and
# token revocation silently degrade to "no limit" and "logout does nothing", and
# a degraded security control that logs a warning is not a control.
REDIS_REQUIRED = _flag("REDIS_REQUIRED", "false" if is_development() else "true")
REDIS_KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", APP_SLUG)
REDIS_SOCKET_TIMEOUT = _int("REDIS_SOCKET_TIMEOUT", 5)

RATE_LIMIT_ENABLED = _flag("RATE_LIMIT_ENABLED", "true")
RATE_LIMIT_DEFAULT = os.getenv("RATE_LIMIT_DEFAULT", "120/minute")
RATE_LIMIT_LOGIN = os.getenv("RATE_LIMIT_LOGIN", "10/minute")

CACHE_ENABLED = _flag("CACHE_ENABLED", "true")
CACHE_DEFAULT_TTL = _int("CACHE_DEFAULT_TTL", 300)

# Background jobs (RQ). `flask jobs worker` consumes these queues in order.
JOBS_ENABLED = _flag("JOBS_ENABLED", "true")
JOB_QUEUES = [q.strip() for q in os.getenv("JOB_QUEUES", "high,default,low").split(",") if q.strip()]
JOB_DEFAULT_TIMEOUT = _int("JOB_DEFAULT_TIMEOUT", 600)
JOB_RESULT_TTL = _int("JOB_RESULT_TTL", 86400)

# ─────────────────────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────────────────────
FRONTEND_URL = os.getenv("FRONTEND_URL", "")
# Browser origins allowed to call the API. Defaults to FRONTEND_URL, or none at
# all (same-origin), which is what the production image serves. NEVER pair "*"
# with credentials — app/__init__.py refuses that combination.
CORS_ORIGINS = os.getenv("CORS_ORIGINS", FRONTEND_URL.rstrip("/") if FRONTEND_URL else "")
JSON_SORT_KEYS = _flag("JSON_SORT_KEYS")
MAX_CONTENT_LENGTH = _int("MAX_CONTENT_LENGTH", 16 * 1024 * 1024)

# ─────────────────────────────────────────────────────────────────────────────
# Logging  (app/logging_setup.py)
# ─────────────────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOG_DIR = Path(os.getenv("LOG_DIR", str(BASE_DIR / "logs")))
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").strip().lower()   # text | json
LOG_TO_FILE = _flag("LOG_TO_FILE", "true")
LOG_TO_CONSOLE = _flag("LOG_TO_CONSOLE", "true")
LOG_MAX_BYTES = _int("LOG_MAX_BYTES", 10 * 1024 * 1024)
LOG_BACKUP_COUNT = _int("LOG_BACKUP_COUNT", 10)
LOG_REQUEST_HEADER = os.getenv("LOG_REQUEST_HEADER", "X-Request-ID")
