"""Unit tests for the JWT helper and the user-level token path overrides."""

from __future__ import annotations

import base64
import json


def b64url(obj: dict) -> str:
    raw = json.dumps(obj).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def make_jwt(exp: float) -> str:
    header = b64url({"alg": "none"})
    payload = b64url({"sub": "u", "name": "n", "iat": 0, "nbf": 0, "exp": exp})
    return f"{header}.{payload}.sig"


def test_jwt_exp_reads_exp_claim():
    from bhoonidhi_cli import jwt_exp

    assert jwt_exp(make_jwt(1_893_456_000)) == 1_893_456_000


def test_jwt_exp_handles_missing_claim_and_garbage():
    from bhoonidhi_cli import jwt_exp

    assert jwt_exp(make_jwt_bad()) is None
    assert jwt_exp("not-a-jwt") is None


def make_jwt_bad() -> str:
    # a "valid" JWT shape whose payload has no exp
    head = b64url({"alg": "none"})
    body = b64url({"sub": "u"})
    return f"{head}.{body}.sig"


def test_token_dir_respects_env_override(monkeypatch, tmp_path):
    from bhoonidhi_cli import token_dir

    monkeypatch.setenv("BHOONIDHI_TOKEN_DIR", str(tmp_path))
    assert token_dir() == tmp_path / "bhoonidhi_cli"


def test_token_dir_defaults_to_xdg_config(monkeypatch, tmp_path):
    from bhoonidhi_cli import token_dir

    monkeypatch.delenv("BHOONIDHI_TOKEN_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert token_dir() == tmp_path / "xdg" / "bhoonidhi_cli"


def test_default_out_dir_respects_env_override(monkeypatch, tmp_path):
    from bhoonidhi_cli import default_out_dir

    monkeypatch.setenv("BHOONIDHI_OUT", str(tmp_path / "dl"))
    assert default_out_dir() == tmp_path / "dl"
