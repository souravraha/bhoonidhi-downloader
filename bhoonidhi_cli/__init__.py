"""bhoonidhi-cli — search & download LISS-4 products from the Bhoonidhi (NRSC) API.

A standalone, stdlib-only Python package (Python 3.11+, no runtime
dependencies) that talks to the official Bhoonidhi API:

    auth    POST https://bhoonidhi-api.nrsc.gov.in/auth/token
    search  POST https://bhoonidhi-api.nrsc.gov.in/data/search
    item    GET  https://bhoonidhi-api.nrsc.gov.in/data/collections/{col}/items/{id}
    fetch   GET  https://bhoonidhi-api.nrsc.gov.in/download?id=...&collection=...

Use it as a command (``bhoonidhi``), as a module (``python -m bhoonidhi_cli``),
or as a library (``from bhoonidhi_cli import Session, search, downloads``).

A registered Bhoonidhi account is required:
<https://bhoonidhi.nrsc.gov.in/bhoonidhi/login.html>.

The public API is flat — everything below is importable from the top level::

    from bhoonidhi_cli import Session, search, with_details, summarize, downloads
    from bhoonidhi_cli import cli
"""

from __future__ import annotations

from . import auth, download  # noqa: F401  (exposed as bhoonidhi_cli.auth / .download)
from ._constants import (
    BENCHMARK_SITES,
    LISS4_COLLECTIONS,
    __version__,
    default_out_dir,
    token_dir,
    token_file,
)
from ._log import log
from .api import build_query, polygon_around, search, summarize, with_details
from .auth import Session, ensure_token, invalidate_cache, jwt_exp
from .cli import main, parse_args
from .download import RateGate, download_one, downloads

__all__ = [
    "__version__",
    "BENCHMARK_SITES",
    "LISS4_COLLECTIONS",
    "auth",
    "build_query",
    "default_out_dir",
    "download_one",
    "download",
    "downloads",
    "ensure_token",
    "invalidate_cache",
    "jwt_exp",
    "log",
    "main",
    "parse_args",
    "polygon_around",
    "RateGate",
    "search",
    "Session",
    "summarize",
    "token_dir",
    "token_file",
    "with_details",
]
