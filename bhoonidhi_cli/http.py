"""Low-level HTTP helpers for the Bhoonidhi (NRSC) API.

Pure stdlib (``urllib``). Returns ``(status, headers, body-bytes)`` rather than
raising on HTTP error codes, so callers can branch on 401/429/etc. Explicitly.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ._constants import USER_AGENT


def request(
    url: str,
    body: dict | None = None,
    token: str | None = None,
    method: str | None = None,
    timeout: int = 60,
) -> tuple[int, dict, bytes]:
    """Perform a request and return ``(status, headers, body_bytes)``.

    HTTP error codes (4xx/5xx) do not raise — they are returned in ``status`` —
    so callers can implement retry/backoff/401 logic deterministically. Only
    transport-level failures (``URLError``, timeout) propagate.
    """
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=data, headers=headers, method=method or ("POST" if data else "GET")
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def open_stream(url: str, token: str) -> urllib.request.Request:
    """Build a Request for a streamed download (caller ``urlopen``s it)."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", USER_AGENT)
    return req
