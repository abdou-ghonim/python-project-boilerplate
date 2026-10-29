"""Account commands for the `local` auth provider."""
from __future__ import annotations

import click
from flask.cli import with_appcontext

import config
from app.models import ROLES, User, db


def seed_default_admin(force: bool = False) -> User | None:
    """Create DEFAULT_ADMIN_USERNAME if no admin exists yet.

    Refuses the placeholder password outside development. A fresh install with a
    known admin password is a backdoor, and it is exactly the step that gets
    skipped when the app "just works" after deployment.
    """
    existing = db.session.query(User).filter_by(username=config.DEFAULT_ADMIN_USERNAME).first()
    if existing and not force:
        click.echo(f"Admin {existing.username} already exists.")
        return existing

    if config.DEFAULT_ADMIN_PASSWORD == config.INSECURE_ADMIN_PASSWORD \
            and not config.is_development():
        click.secho(
            "Refusing to create the default admin: DEFAULT_ADMIN_PASSWORD is still "
            "the placeholder and this is not a development environment. Set it to a "
            "real password, or create the account with `flask create-user`.",
            fg="red")
        return None

    user = existing or User(username=config.DEFAULT_ADMIN_USERNAME)
    user.email = config.DEFAULT_ADMIN_USERNAME if "@" in config.DEFAULT_ADMIN_USERNAME else None
    user.display_name = "Administrator"
    user.role = "admin"
    user.auth_provider = "local"
    user.is_active = True
    user.set_password(config.DEFAULT_ADMIN_PASSWORD)
    db.session.add(user)
    db.session.commit()

    click.secho(f"Created admin {user.username}", fg="green")
    if config.DEFAULT_ADMIN_PASSWORD == config.INSECURE_ADMIN_PASSWORD:
        click.secho(f"  Password is the placeholder {config.INSECURE_ADMIN_PASSWORD!r} — "
                    "change it before this leaves your machine.", fg="yellow")
    return user


@click.command(name="create-admin")
@click.option("--force", is_flag=True, help="Reset the password if the account exists.")
@with_appcontext
def create_admin(force: bool) -> None:
    """Create (or reset) the default admin from DEFAULT_ADMIN_* config."""
    seed_default_admin(force=force)


@click.command(name="create-user")
@click.option("--username", prompt=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--role", type=click.Choice(ROLES), default="user", show_default=True)
@click.option("--email", default=None)
@click.option("--name", "display_name", default=None)
@with_appcontext
def create_user(username: str, password: str, role: str, email: str | None,
                display_name: str | None) -> None:
    """Create a local account interactively."""
    if db.session.query(User).filter_by(username=username).first():
        raise click.ClickException(f"User {username} already exists.")

    user = User(username=username, email=email or (username if "@" in username else None),
                display_name=display_name, role=role, auth_provider="local")
    try:
        user.set_password(password)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    db.session.add(user)
    db.session.commit()
    click.secho(f"Created {role} {username}", fg="green")


@click.command(name="list-users")
@with_appcontext
def list_users() -> None:
    """List accounts."""
    users = db.session.query(User).order_by(User.username).all()
    if not users:
        click.echo("No users. Run `flask create-admin`.")
        return
    click.echo(f"{'USERNAME':<34}{'ROLE':<10}{'PROVIDER':<10}{'ACTIVE':<8}LAST LOGIN")
    for user in users:
        last = user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else "never"
        click.echo(f"{user.username:<34}{user.role:<10}{user.auth_provider:<10}"
                   f"{'yes' if user.is_active else 'no':<8}{last}")


@click.command(name="set-role")
@click.argument("username")
@click.argument("role", type=click.Choice(ROLES))
@with_appcontext
def set_role(username: str, role: str) -> None:
    """Change a user's role and end their existing sessions."""
    user = db.session.query(User).filter_by(username=username).first()
    if user is None:
        raise click.ClickException(f"No such user: {username}")
    user.role = role
    db.session.commit()

    # Existing tokens carry the old role in their claims. The per-user cut-off
    # forces a fresh sign-in rather than letting stale privileges run to expiry.
    from app.auth import revoke_all_for_user
    revoke_all_for_user(str(user.id))
    click.secho(f"{username} is now {role}; existing sessions revoked.", fg="green")
