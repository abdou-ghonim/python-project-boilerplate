"""Background work: the queue, and the tasks that run on it.

Thin on purpose. The queue is Redis plus a function reference, and wrapping it
further would hide the one thing worth knowing — that without Redis there is no
queue, and a caller must decide whether to run the work inline or fail.

A task is an ordinary function: `enqueue(example_task, 3)` puts it on a queue and
`flask jobs worker` runs it in another process. Keep them importable at module
level — RQ serialises the reference, not the function body, so a closure or a
nested function cannot be enqueued.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import config
from app.redis import get_redis_binary

logger = logging.getLogger(__name__)


class QueueUnavailable(RuntimeError):
    """Raised when work cannot be queued because Redis is not reachable."""


# ── The queue ────────────────────────────────────────────────────────────────
def get_queue(name: str = "default"):
    if not config.JOBS_ENABLED:
        raise QueueUnavailable(
            "Background jobs are turned off (JOBS_ENABLED=false). Run the work "
            "inline, or turn them back on.")
    # RQ needs the undecoded connection: job payloads are pickled bytes.
    client = get_redis_binary()
    if client is None:
        raise QueueUnavailable(
            "Background jobs need Redis. Start it, set REDIS_URL, or run the work "
            "inline instead of enqueueing it.")
    from rq import Queue
    return Queue(name, connection=client, default_timeout=config.JOB_DEFAULT_TIMEOUT)


def enqueue(func: Callable, *args, queue: str = "default", **kwargs) -> Any:
    """Queue `func(*args, **kwargs)` for a worker. Returns the RQ job."""
    job = get_queue(queue).enqueue(func, *args, result_ttl=config.JOB_RESULT_TTL,
                                   **kwargs)
    logger.info("Enqueued %s on %s as %s", getattr(func, "__name__", func), queue,
                job.id)
    return job


def queue_stats() -> dict:
    """Depth of each configured queue, for a status command or a dashboard."""
    if not config.JOBS_ENABLED:
        return {"enabled": False}
    try:
        return {name: len(get_queue(name)) for name in config.JOB_QUEUES}
    except QueueUnavailable as exc:
        return {"error": str(exc)}


# ── The tasks ────────────────────────────────────────────────────────────────
def example_task(seconds: int = 1, label: str = "demo") -> dict:
    """Stand-in for real work, so the queue wiring can be exercised end to end."""
    logger.info("Task %s started (%ss)", label, seconds)
    time.sleep(seconds)
    logger.info("Task %s finished", label)
    return {"label": label, "slept": seconds}


def rebuild_item_summary() -> dict:
    """Recompute the cached item summary.

    Shows the pattern worth copying: a task runs inside an app context it creates
    itself, because the worker process has none.
    """
    from app import create_app
    from app.redis import cache_invalidate
    from app.services.item_service import CACHE_NAMESPACE, ItemService

    app = create_app()
    with app.app_context():
        cache_invalidate(CACHE_NAMESPACE)
        return ItemService.summary()
