"""OpenID Connect against an external IdP (Entra ID, Google, Keycloak, Okta…).

The browser is redirected to the IdP, comes back to /api/auth/callback with a
code, and we exchange it for an ID token. From there the flow rejoins the local
provider's: a row in the user table, and one of our own JWTs. The SPA never handles
the IdP's tokens.
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

from flask import Blueprint, jsonify, redirect, request

import config
from app.models import User, db
from app.redis import get_redis, key

from . import AuthError, AuthProvider, bearer_token, require_auth
from .tokens import TokenError, decode_token, issue_token, revoke_token

logger = logging.getLogger(__name__)


class OIDCAuthProvider(AuthProvider):
    name = "oidc"
    login_style = "redirect"

    def __init__(self) -> None:
        self._oauth = None
        self._client = None

    # ── Startup ──────────────────────────────────────────────────────────────
    def init_app(self, app) -> None:
        missing = [n for n, v in (
            ("OIDC_DISCOVERY_URL", config.OIDC_DISCOVERY_URL),
            ("OIDC_CLIENT_ID", config.OIDC_CLIENT_ID),
            ("OIDC_CLIENT_SECRET", config.OIDC_CLIENT_SECRET),
        ) if not v]
        if missing:
            raise RuntimeError(
                f"AUTH_PROVIDER=oidc needs {', '.join(missing)}. Set them in the "
                "environment, or switch AUTH_PROVIDER to local."
            )
        try:
            from authlib.integrations.flask_client import OAuth
        except ImportError as exc:
            raise RuntimeError(
                "AUTH_PROVIDER=oidc needs Authlib. Run: pip install -r requirements/oidc.txt"
            ) from exc

        self._oauth = OAuth(app)
        self._client = self._oauth.register(
            name="oidc",
            client_id=config.OIDC_CLIENT_ID,
            client_secret=config.OIDC_CLIENT_SECRET,
            server_metadata_url=config.OIDC_DISCOVERY_URL,
            client_kwargs={"scope": config.OIDC_SCOPES},
        )
        logger.info("OIDC provider configured against %s", config.OIDC_DISCOVERY_URL)

    # ── Login state ──────────────────────────────────────────────────────────
    # state/nonce are kept in Redis rather than the session cookie so the
    # callback works whichever gunicorn worker handles it, and so the entry
    # expires on its own if the user abandons the login.
    def _remember_state(self, state: str, nonce: str, next_url: str) -> None:
        client = get_redis()
        if client is None:
            raise AuthError(
                "OIDC login needs Redis to hold the login state. Start Redis or "
                "set REDIS_URL.", 503)
        client.set(key("oidc-state", state), f"{nonce}|{next_url}",
                   ex=config.OIDC_STATE_TTL_SECONDS)

    def _consume_state(self, state: str) -> tuple[str, str]:
        client = get_redis()
        if client is None:
            raise AuthError("OIDC login state is unavailable.", 503)
        raw = client.getdel(key("oidc-state", state))
        if not raw:
            # Also what an expired login or a replayed callback looks like, and
            # all three deserve the same refusal.
            raise AuthError("Login request expired or was not recognised. Try again.")
        nonce, _, next_url = str(raw).partition("|")
        return nonce, next_url

    # ── Routes ───────────────────────────────────────────────────────────────
    def register_routes(self, bp: Blueprint) -> None:
        @bp.get("/login")
        def login():
            state = secrets.token_urlsafe(32)
            nonce = secrets.token_urlsafe(32)
            next_url = request.args.get("next") or config.OIDC_POST_LOGIN_REDIRECT
            # Only relative paths: an open redirect here would let a phishing
            # link bounce off our domain into the attacker's.
            if not next_url.startswith("/"):
                next_url = config.OIDC_POST_LOGIN_REDIRECT
            self._remember_state(state, nonce, next_url)

            redirect_uri = request.url_root.rstrip("/") + "/api/auth/callback"
            return self._client.authorize_redirect(
                redirect_uri, state=state, nonce=nonce)

        @bp.get("/callback")
        def callback():
            state = request.args.get("state") or ""
            nonce, next_url = self._consume_state(state)

            try:
                token = self._client.authorize_access_token()
                claims = self._client.parse_id_token(token, nonce=nonce)
            except Exception as exc:                            # noqa: BLE001
                logger.warning("OIDC callback failed: %s", exc)
                raise AuthError("Sign-in with the identity provider failed.") from exc

            user = self._sync_user(claims)
            issued = issue_token(user.identity)
            # The SPA reads the token from the fragment and clears it, so it
            # never lands in a server log or a Referer header the way a query
            # parameter would.
            return redirect(f"{next_url}#{urlencode({'access_token': issued['access_token']})}")

        @bp.post("/logout")
        def logout():
            token = bearer_token()
            if token:
                try:
                    revoke_token(decode_token(token))
                except TokenError:
                    pass
            # The IdP session is deliberately left alone: a single-sign-out would
            # end the user's session in every other app behind the same IdP.
            return jsonify({"status": "signed out"})

        @bp.get("/me")
        @require_auth
        def me():
            from flask import g

            user = db.session.get(User, int(g.current_user["sub"]))
            return jsonify(user.to_dict() if user else g.current_user)

    # ── Identity mapping ─────────────────────────────────────────────────────
    def _sync_user(self, claims: dict) -> User:
        """Upsert the federated identity into the user table.

        Matching is on the IdP's `sub`, never on email: an email address can be
        reassigned to a different person, and matching on it would hand them the
        previous owner's account.
        """
        subject = claims.get("sub")
        if not subject:
            raise AuthError("The identity provider returned no subject claim.")

        user = db.session.query(User).filter_by(
            external_id=subject, auth_provider=self.name).one_or_none()
        email = claims.get("email") or claims.get("preferred_username")
        if user is None:
            user = User(
                username=email or f"{self.name}:{subject}",
                external_id=subject,
                auth_provider=self.name,
                role=self._role_from(claims),
            )
            db.session.add(user)
            logger.info("Created federated user %s", user.username)

        user.email = email
        user.display_name = claims.get("name") or user.display_name
        # Roles are re-read on every login: a group removed in the IdP must take
        # effect here, which it would not if we only set the role at creation.
        user.role = self._role_from(claims)
        user.touch_login()
        db.session.commit()

        if not user.is_active:
            raise AuthError("This account has been disabled.", 403)
        return user

    def _role_from(self, claims: dict) -> str:
        from app.models import ROLES

        raw = claims.get(config.OIDC_ROLE_CLAIM)
        values = [raw] if isinstance(raw, str) else list(raw or [])
        # Take the highest role the IdP asserts that this app understands;
        # anything unrecognised falls back to the configured default.
        known = [v.lower() for v in values if isinstance(v, str) and v.lower() in ROLES]
        if not known:
            return config.OIDC_DEFAULT_ROLE
        return max(known, key=ROLES.index)

    def public_config(self) -> dict:
        return {**super().public_config(), "login_url": "/api/auth/login"}

    def authenticate_request(self, claims: dict) -> dict:
        user = db.session.get(User, int(claims.get("sub", 0) or 0))
        if user is None or not user.is_active:
            raise AuthError("This account is no longer active.", 403)
        claims["role"] = user.role
        return claims
