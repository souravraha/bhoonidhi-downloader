"""Auth: password / refresh-token grants, JWT cache, re-auth on HTTP 401.

Credentials come from ``BHOONIDHI_USER`` / ``BHOONIDHI_PASS`` (or the
``--user`` / ``--passwd`` flags; the password is prompted if omitted). The JWT
is cached in ``token_file()`` (mode 600 — see :mod:`bhoonidhi_cli._constants`)
and refreshed automatically when it expires. The password is held in memory
only for the life of the process and never written to disk.
"""

from __future__ import annotations

import base64
import contextlib
from datetime import UTC, datetime
import getpass
import json
import os
import time

from . import http
from ._constants import TOKEN_URL, token_file
from ._log import log


def jwt_exp(token: str) -> float | None:
    """Parse the ``exp`` claim out of a JWT (no signature verification)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (ValueError, KeyError, TypeError, IndexError):
        return None


def _auth_request(user: str, body: dict) -> tuple[int, bytes]:
    status, _, raw = http.request(TOKEN_URL, body=body)
    if status in (429, 500, 503):
        log(f"auth endpoint busy/rate-limited (HTTP {status}); retrying in 60 s")
        time.sleep(60)
        return _auth_request(user, body)
    return status, raw


def _load_token_cache(user: str) -> dict:
    defaults = {
        "user": user,
        "access_token": "",
        "refresh_token": "",
        "expires_at": 0.0,
    }
    path = token_file()
    if path.exists():
        try:
            cached = json.loads(path.read_text())
        except (OSError, ValueError, KeyError):
            return defaults
        if (
            isinstance(cached, dict)
            and cached.get("user") == user
            and cached.get("access_token")
        ):
            return {**defaults, **cached}
    return defaults


def _save_token_cache(user: str, tok: dict) -> None:
    now = time.time()
    expires_at = jwt_exp(tok["access_token"]) or (now + tok.get("expires_in", 3600))
    path = token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "user": user,
                "access_token": tok["access_token"],
                "refresh_token": tok.get("refresh_token", ""),
                "expires_at": expires_at,
                "saved": datetime.now(UTC).isoformat(),
            }
        )
    )
    os.chmod(path, 0o600)


def ensure_token(user: str, passwd: str | None) -> str:
    """Return a valid access token for ``user``, logging in if needed."""
    cache = _load_token_cache(user)
    now = time.time()
    if cache.get("access_token") and cache.get("expires_at", 0) > now + 60:
        log("reusing cached access token")
        return cache["access_token"]

    # 1) try a silent refresh with the stored refresh token (no password needed)
    if cache.get("refresh_token"):
        log("access token expired -> refreshing with refresh token")
        status, raw = _auth_request(
            user,
            {
                "userId": user,
                "refresh_token": cache["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        if status == 200:
            tok = json.loads(raw)
            if tok.get("access_token"):
                _save_token_cache(user, tok)
                log("refreshed access token OK")
                return tok["access_token"]

    # 2) plain password grant (prompts if not present)
    if passwd is None:
        passwd = getpass.getpass(f"Bhoonidhi password for '{user}': ")
    log("authenticating (POST /auth/token)")
    status, raw = _auth_request(
        user, {"userId": user, "password": passwd, "grant_type": "password"}
    )
    if status != 200:
        raise SystemExit(f"authentication failed (HTTP {status}): {raw[:400]!r}")
    tok = json.loads(raw)
    if not tok.get("access_token"):
        raise SystemExit(f"unexpected auth response: {raw[:400]!r}")
    _save_token_cache(user, tok)
    return tok["access_token"]


def invalidate_cache(user: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        token_file().unlink()
    log("deleted cached token — next auth request will re-login")


class Session:
    """Holds the current access token and transparently re-authenticates on 401.

    The password is kept in memory only for the lifetime of this process; it
    is never written to disk.
    """

    def __init__(self, user: str, passwd: str | None = None):
        self.user = user
        self.passwd = passwd
        self.token = ensure_token(user, passwd)

    def handle_401(self) -> None:
        log("token rejected by server (HTTP 401) — re-authenticating once")
        invalidate_cache(self.user)
        self.token = ensure_token(self.user, self.passwd)
