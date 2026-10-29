"""Redis, and the four things this application does with it.

    connection      one decoded client, plus an undecoded one for RQ
    caching         @cached, with namespace invalidation
    rate limiting   @rate_limit, and the login lockout's direct counter
    locks           redis_lock(), so replicated workers do not double-run a job

They live together because they are one decision: REDIS_ENABLED=false turns all
of them into no-ops, and deleting this file deletes the lot. Token revocation is
the fifth user and lives in app/auth/tokens.py, next to the tokens it revokes.

Whether Redis is reachable is a question about the application's security
posture, not just its performance — rate limiting that silently stops limiting
is worse than an outage, because nothing reports it. Outside development
REDIS_REQUIRED makes an unreachable server a boot failure. In development each
consumer falls back to an in-process implementation and says so, so `flask run`
works with nothing else installed.

(The module is `app.redis`; `import redis` inside it still finds the driver,
because Python 3 imports are absolute.)
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable

from flask import g, jsonify, request

import config

logger = logging.getLogger(__name__)

_client = None
_checked = False
_binary_client = None
_binary_checked = False


# ─────────────────────────────────────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────────────────────────────────────
def get_redis():
    """The shared client, or None when Redis is off or unavailable.

    REDIS_ENABLED=false is the deliberate case and short-circuits everything,
    REDIS_REQUIRED included: an operator who turned Redis off does not want a
    boot failure telling them it is missing.
    """
    global _client, _checked
    if _checked:
        return _client
    if not config.REDIS_ENABLED:
        return None

    _checked = True
    try:
        import redis
    except ImportError:
        if config.REDIS_REQUIRED:
            raise RuntimeError(
                "REDIS_REQUIRED is set but the redis package is not installed. "
                "Run: pip install -r requirements.txt") from None
        logger.warning("redis package not installed; Redis-backed features are off.")
        return None

    try:
        client = redis.Redis.from_url(
            config.REDIS_URL,
            decode_responses=True,
            socket_timeout=config.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=config.REDIS_SOCKET_TIMEOUT,
            health_check_interval=30,
        )
        client.ping()
    except Exception as exc:                                    # noqa: BLE001
        if config.REDIS_REQUIRED:
            raise RuntimeError(
                f"Cannot reach Redis at {config.REDIS_URL}: {exc}. Rate limiting and "
                "token revocation depend on it, so this is fatal outside development. "
                "Start Redis, fix REDIS_URL, or set REDIS_REQUIRED=false to accept "
                "degraded in-process fallbacks.") from exc
        logger.warning(
            "Redis unavailable at %s (%s). Falling back to in-process rate limiting "
            "and caching; logout will not revoke tokens across workers.",
            config.REDIS_URL, exc)
        return None

    _client = client
    logger.info("Redis connected: %s", config.REDIS_URL)
    return _client


def get_redis_binary():
    """A second client that does NOT decode responses, for RQ.

    RQ stores pickled job payloads and reads them back as bytes. The shared
    client above decodes every reply to str, which corrupts them — so the job
    queue gets its own connection rather than everything else losing the
    convenience of decoded strings.
    """
    global _binary_client, _binary_checked
    if _binary_checked:
        return _binary_client
    if not config.REDIS_ENABLED:
        return None

    _binary_checked = True
    # The decoded client is created first so that its connection check, logging
    # and REDIS_REQUIRED behaviour apply once, in one place.
    if get_redis() is None:
        return None

    import redis
    try:
        client = redis.Redis.from_url(
            config.REDIS_URL,
            decode_responses=False,
            socket_timeout=config.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=config.REDIS_SOCKET_TIMEOUT,
            health_check_interval=30,
        )
        client.ping()
    except Exception as exc:                                    # noqa: BLE001
        logger.error("Cannot open the binary Redis connection used by jobs: %s", exc)
        return None

    _binary_client = client
    return _binary_client


def key(*parts: str) -> str:
    """Namespaced key, so several apps can share one Redis database safely."""
    return ":".join((config.REDIS_KEY_PREFIX, *(str(p) for p in parts)))


def reset_client_cache() -> None:
    """Forget the cached clients. Used by tests and by `flask db-check`."""
    global _client, _checked, _binary_client, _binary_checked
    _client = None
    _checked = False
    _binary_client = None
    _binary_checked = False


def health() -> dict:
    """Shape used by GET /health."""
    if not config.REDIS_ENABLED:
        return {"enabled": False, "connected": False, "required": False}
    client = get_redis()
    if client is None:
        return {"connected": False, "required": config.REDIS_REQUIRED}
    try:
        info = client.info("server")
        return {"connected": True, "required": config.REDIS_REQUIRED,
                "version": info.get("redis_version")}
    except Exception as exc:                                    # noqa: BLE001
        return {"connected": False, "required": config.REDIS_REQUIRED, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Caching
#
# Deliberately not Flask-Caching: the requirement is a decorator and a way to
# drop a group of keys, and this keeps the serialisation format (JSON, not
# pickle) visible and safe to read from another process or another language.
# ─────────────────────────────────────────────────────────────────────────────
def cache_get(namespace: str, name: str) -> Any | None:
    client = get_redis()
    if client is None or not config.CACHE_ENABLED:
        return None
    try:
        raw = client.get(key("cache", namespace, name))
        return json.loads(raw) if raw else None
    except Exception as exc:                                    # noqa: BLE001
        logger.debug("Cache read failed for %s/%s: %s", namespace, name, exc)
        return None


def cache_set(namespace: str, name: str, value: Any, ttl: int | None = None) -> None:
    client = get_redis()
    if client is None or not config.CACHE_ENABLED:
        return
    try:
        client.set(key("cache", namespace, name),
                   json.dumps(value, default=str),
                   ex=ttl or config.CACHE_DEFAULT_TTL)
    except Exception as exc:                                    # noqa: BLE001
        logger.debug("Cache write failed for %s/%s: %s", namespace, name, exc)


def cache_invalidate(namespace: str) -> int:
    """Drop every key in a namespace. Returns how many were removed.

    SCAN rather than KEYS: KEYS blocks the server for the length of the keyspace
    scan, which on a shared Redis is everyone's problem.
    """
    client = get_redis()
    if client is None:
        return 0
    pattern = key("cache", namespace, "*")
    removed = 0
    try:
        for batch in _scan_batches(client, pattern):
            removed += client.delete(*batch)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("Cache invalidation failed for %s: %s", namespace, exc)
    return removed


def cached(namespace: str, ttl: int | None = None) -> Callable:
    """Memoise a function's JSON-serialisable return value in Redis.

        @cached("items", ttl=60)
        def list_items(page: int): ...
        list_items.invalidate()          # after a write
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            name = f"{func.__name__}:{_fingerprint(args, kwargs)}"
            hit = cache_get(namespace, name)
            if hit is not None:
                return hit
            value = func(*args, **kwargs)
            cache_set(namespace, name, value, ttl)
            return value

        wrapper.invalidate = lambda: cache_invalidate(namespace)  # type: ignore[attr-defined]
        return wrapper

    return decorator


def _fingerprint(args: tuple, kwargs: dict) -> str:
    raw = json.dumps([args, sorted(kwargs.items())], default=str, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _scan_batches(client, pattern: str, size: int = 500):
    cursor, batch = 0, []
    while True:
        cursor, keys = client.scan(cursor=cursor, match=pattern, count=size)
        batch.extend(keys)
        if len(batch) >= size or cursor == 0:
            if batch:
                yield batch
                batch = []
        if cursor == 0:
            return


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting
#
# An in-process counter limits each gunicorn worker separately: with four
# workers a "5 attempts" lockout accepts twenty, and a restart forgets
# everything. Counting in Redis is the only version of this that is actually a
# control.
#
#     @bp.post("/login")
#     @rate_limit(config.RATE_LIMIT_LOGIN, by="ip")
#     def login(): ...
# ─────────────────────────────────────────────────────────────────────────────
_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}

#: Fallback store when Redis is absent (development only): {key: [timestamps]}.
_rate_local: dict[str, list[float]] = {}


def parse_limit(spec: str) -> tuple[int, int]:
    """Parse "10/minute" into (10, 60). Raises on a malformed spec."""
    try:
        count, _, unit = spec.partition("/")
        unit = unit.strip().lower().rstrip("s") or "minute"
        return int(count), _UNITS[unit]
    except (ValueError, KeyError) as exc:
        raise ValueError(
            f"Invalid rate limit {spec!r}. Expected '<count>/<second|minute|hour|day>'."
        ) from exc


def client_ip() -> str:
    """Best-effort client address, honouring one proxy hop."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def hit(bucket: str, spec: str) -> tuple[bool, int, int]:
    """Record one hit against a "<count>/<unit>" limit."""
    limit, window = parse_limit(spec)
    return hit_window(bucket, limit, window)


def hit_window(bucket: str, limit: int, window: int) -> tuple[bool, int, int]:
    """Record one hit. Returns (allowed, remaining, retry_after_seconds).

    Honours RATE_LIMIT_ENABLED here as well as in the decorator, because the
    login lockout calls this directly — a flag that only half of the callers
    respect is worse than no flag.

    A fixed window is used deliberately: it costs one INCR and one EXPIRE, and
    the burst it permits at a window boundary does not matter for the thing this
    protects against — automated repetition over minutes, not milliseconds.
    """
    if not config.RATE_LIMIT_ENABLED:
        return True, limit, 0
    client = get_redis()
    now = time.time()

    if client is None:
        hits = [t for t in _rate_local.get(bucket, []) if now - t < window]
        hits.append(now)
        _rate_local[bucket] = hits
        used = len(hits)
        return used <= limit, max(0, limit - used), window

    slot = int(now // window)
    redis_key = key("ratelimit", bucket, slot)
    try:
        pipe = client.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window)
        used, _ = pipe.execute()
    except Exception as exc:                                    # noqa: BLE001
        # Never let a Redis blip turn into a 500 on every route. Logged loudly
        # because an unreported failure here means no limiting at all.
        logger.error("Rate limit check failed (allowing request): %s", exc)
        return True, limit, window

    retry_after = int((slot + 1) * window - now)
    return int(used) <= limit, max(0, limit - int(used)), retry_after


def rate_limit(spec: str | Callable[[], str] | None = None, *, by: str = "ip",
               scope: str | None = None):
    """Limit a view to `spec` requests per window, keyed by IP or by user.

    `spec` may be a callable, which is resolved on each request. A plain string
    read from config at import time freezes the limit for the life of the
    process, so a settings change needs a restart to take effect.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not config.RATE_LIMIT_ENABLED:
                return view(*args, **kwargs)

            limit_spec = spec() if callable(spec) else (spec or config.RATE_LIMIT_DEFAULT)
            bucket = f"{scope or request.endpoint or view.__name__}:{_identity(by)}"
            allowed, remaining, retry_after = hit(bucket, limit_spec)

            if not allowed:
                logger.warning("Rate limit exceeded on %s by %s", bucket, _identity(by))
                response = jsonify({
                    "error": "Too many requests. Slow down and try again shortly.",
                    "status": 429,
                    "retry_after": retry_after,
                })
                response.status_code = 429
                response.headers["Retry-After"] = str(retry_after)
                return response

            response = view(*args, **kwargs)
            # Headers help a well-behaved client back off before it is refused.
            try:
                response = _ensure_response(response)
                response.headers["X-RateLimit-Limit"] = limit_spec
                response.headers["X-RateLimit-Remaining"] = str(remaining)
            except Exception:                                   # noqa: BLE001
                pass
            return response

        return wrapper

    return decorator


def reset_limit(bucket: str, window: int | None = None) -> None:
    """Clear a bucket — used after a successful login to forget failed attempts.

    `window` must match the one the bucket was counted with, since the key
    carries the window slot.
    """
    client = get_redis()
    _rate_local.pop(bucket, None)
    if client is None:
        return
    window = window or parse_limit(config.RATE_LIMIT_DEFAULT)[1]
    try:
        slot = int(time.time() // window)
        client.delete(key("ratelimit", bucket, slot))
    except Exception as exc:                                    # noqa: BLE001
        logger.debug("Could not reset rate-limit bucket %s: %s", bucket, exc)


def _identity(by: str) -> str:
    if by == "user":
        user = getattr(g, "current_user", None) or {}
        return str(user.get("sub") or client_ip())
    return client_ip()


def _ensure_response(result):
    from flask import current_app
    return current_app.make_response(result)


# ─────────────────────────────────────────────────────────────────────────────
# Locks
#
# A scheduled command running in three replicas runs three times unless
# something arbitrates. SET NX EX is that arbiter: one holder, and an expiry so
# a worker killed mid-task does not hold the lock for ever.
# ─────────────────────────────────────────────────────────────────────────────
# Releasing by value, not just by key: a lock whose TTL expired may already be
# held by someone else, and deleting it blindly would release *their* lock.
_RELEASE = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class LockNotAcquired(RuntimeError):
    """Raised by redis_lock(..., blocking=False) when another holder has it."""


@contextmanager
def redis_lock(name: str, *, ttl: int = 300, blocking: bool = False,
               timeout: int = 30, poll: float = 0.25):
    """Hold a named lock for the duration of the block.

        with redis_lock("nightly-sync", ttl=1800):
            run_sync()

    With no Redis the lock is a no-op and a warning: in development that is the
    right trade, but a deployment that genuinely needs mutual exclusion should
    run with REDIS_REQUIRED=true, which makes a missing Redis fatal at startup.
    """
    client = get_redis()
    if client is None:
        logger.warning("No Redis: lock %r is not enforced.", name)
        yield True
        return

    lock_key = key("lock", name)
    token = uuid.uuid4().hex
    deadline = time.monotonic() + timeout
    acquired = False

    while True:
        acquired = bool(client.set(lock_key, token, nx=True, ex=ttl))
        if acquired or not blocking or time.monotonic() >= deadline:
            break
        time.sleep(poll)

    if not acquired:
        if blocking:
            raise LockNotAcquired(
                f"Timed out after {timeout}s waiting for lock {name!r}.")
        raise LockNotAcquired(f"Lock {name!r} is held by another worker.")

    logger.debug("Acquired lock %s", name)
    try:
        yield True
    finally:
        try:
            client.eval(_RELEASE, 1, lock_key, token)
        except Exception as exc:                                # noqa: BLE001
            # The TTL is the backstop; log rather than mask the body's exception.
            logger.warning("Could not release lock %s (expires in <=%ss): %s",
                           name, ttl, exc)
