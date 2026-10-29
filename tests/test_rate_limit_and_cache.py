"""Rate limiting, caching and locks degrade predictably without Redis."""
from __future__ import annotations

import pytest

import config


def test_rate_limit_refuses_after_the_limit(app, client, monkeypatch):
    from app import redis

    redis._rate_local.clear()
    monkeypatch.setattr(config, "RATE_LIMIT_LOGIN", "3/minute")

    statuses = [
        client.post("/api/auth/login",
                    json={"username": "nobody@example.com", "password": "x"}).status_code
        for _ in range(5)
    ]
    assert 429 in statuses
    # The 429 must be the refusal, not a knock-on failure.
    assert statuses.index(429) >= 3


def test_parse_limit_accepts_the_documented_forms():
    from app.redis import parse_limit

    assert parse_limit("10/minute") == (10, 60)
    assert parse_limit("5/second") == (5, 1)
    assert parse_limit("100/hour") == (100, 3600)


def test_cache_round_trip(app):
    """With Redis, a value round-trips and invalidation removes it.

    Without Redis every call is a silent no-op — which is the behaviour that
    lets the suite, and `flask run`, work with nothing else installed.
    """
    from app.redis import cache_get, cache_invalidate, cache_set, get_redis

    cache_set("ns", "key", {"a": 1})

    if get_redis() is None:
        assert cache_get("ns", "key") is None
        assert cache_invalidate("ns") == 0
        return

    assert cache_get("ns", "key") == {"a": 1}
    assert cache_invalidate("ns") == 1
    assert cache_get("ns", "key") is None


def test_lock_is_exclusive(app):
    """A second acquisition of a held lock is refused, not silently granted."""
    import pytest

    from app.redis import LockNotAcquired, get_redis, redis_lock

    with redis_lock("demo", ttl=30) as held:
        assert held is True
        if get_redis() is None:
            return                      # no Redis: documented to be unenforced
        with pytest.raises(LockNotAcquired):
            with redis_lock("demo", ttl=30):
                pass

    # Released at the end of the block, so the next caller gets it.
    with redis_lock("demo", ttl=30):
        pass


def test_request_id_is_echoed_and_honoured(client):
    response = client.get("/health", headers={config.LOG_REQUEST_HEADER: "trace-abc"})
    assert response.headers[config.LOG_REQUEST_HEADER] == "trace-abc"


# ── Turning features off ─────────────────────────────────────────────────────
# Each of these is meant to be droppable: the switch makes the feature a no-op
# rather than an error, so the code that calls it does not have to change before
# the code that implements it is deleted.

def test_redis_disabled_connects_to_nothing(app, monkeypatch):
    import config
    from app import redis as redis_module

    monkeypatch.setattr(config, "REDIS_ENABLED", False)
    monkeypatch.setattr(redis_module, "_checked", False)
    monkeypatch.setattr(redis_module, "_binary_checked", False)
    assert redis_module.get_redis() is None
    assert redis_module.get_redis_binary() is None
    assert redis_module.health() == {"enabled": False, "connected": False,
                                     "required": False}


def test_rate_limiting_disabled_allows_everything(app, monkeypatch):
    import config
    from app.redis import hit_window

    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", False)
    for _ in range(50):
        allowed, _, retry_after = hit_window("anything", 1, 60)
        assert allowed and retry_after == 0


def test_jobs_disabled_refuse_clearly(app, monkeypatch):
    import config
    from app.services.jobs import QueueUnavailable, get_queue, queue_stats

    monkeypatch.setattr(config, "JOBS_ENABLED", False)
    assert queue_stats() == {"enabled": False}
    with pytest.raises(QueueUnavailable, match="turned off"):
        get_queue()
