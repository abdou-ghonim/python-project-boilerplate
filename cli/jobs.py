"""Background job commands (RQ)."""
from __future__ import annotations

import click
from flask.cli import with_appcontext

import config


@click.group(name="jobs")
def jobs() -> None:
    """Run and inspect background workers."""


@jobs.command(name="worker")
@click.argument("queues", nargs=-1)
@click.option("--burst", is_flag=True, help="Exit once the queues are empty.")
@with_appcontext
def worker(queues: tuple[str, ...], burst: bool) -> None:
    """Consume queues until stopped. Queue order is priority order."""
    from rq import Worker

    from app.redis import get_redis_binary

    client = get_redis_binary()
    if client is None:
        raise click.ClickException(
            "No Redis connection — a worker has nothing to consume. Start Redis "
            "or fix REDIS_URL.")

    names = list(queues) or config.JOB_QUEUES
    click.echo(f"Worker starting on: {', '.join(names)}")
    Worker(names, connection=client).work(burst=burst, with_scheduler=True)


@jobs.command(name="status")
@with_appcontext
def status() -> None:
    """Show queue depths."""
    from app.services.jobs import queue_stats

    stats = queue_stats()
    if stats.get("enabled") is False:
        click.secho("Background jobs are off (JOBS_ENABLED=false).", fg="yellow")
        return
    if "error" in stats:
        raise click.ClickException(stats["error"])
    for name, depth in stats.items():
        click.echo(f"{name:<12}{depth} job(s)")


@jobs.command(name="demo")
@click.option("--seconds", default=2, show_default=True)
@with_appcontext
def demo(seconds: int) -> None:
    """Enqueue the example task, to prove the queue end to end."""
    from app.services.jobs import enqueue, example_task

    job = enqueue(example_task, seconds, label="cli-demo")
    click.secho(f"Enqueued {job.id}. Run `flask jobs worker` to process it.", fg="green")
