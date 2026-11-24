"""Shared constants and user-level path helpers for bhoonidhi-cli.

All Bhoonidhi (NRSC) API endpoints, the LISS-4 STAC collections, the PS-10
benchmark sites, the rate-limit tuning knobs, and the user-level locations
(token cache + default download directory).

The token cache and default ``--out`` directory live in the user's home /
XDG-config space (not the repo) so a normal ``pipx install bhoonidhi-cli``
behaves sensibly outside any checkout. Both can be overridden by environment
variables, which is also what the test-suite uses to redirect them.
"""

from __future__ import annotations

import os
from pathlib import Path

__version__ = "0.1.0"

API_BASE = "https://bhoonidhi-api.nrsc.gov.in"
TOKEN_URL = f"{API_BASE}/auth/token"
SEARCH_URL = f"{API_BASE}/data/search"
DOWNLOAD_URL = f"{API_BASE}/download"

USER_AGENT = f"bhoonidhi-cli/{__version__}"

# LISS-4 (ResourceSat-2 / 2A) Level-2 STAC collections.
LISS4_COLLECTIONS = [
    "ResourceSat-2_LISS4-MX70_L2",
    "ResourceSat-2A_LISS4-MX70_L2",
]

# The 6 terrains named in the PS-10 problem statement (BENCHMARK_DATA.md §1).
BENCHMARK_SITES: dict[str, tuple[float, float]] = {
    "himalaya-snow": (74.3909, 34.0531),
    "thar-desert": (70.9543, 26.9027),
    "delhi-urban": (77.6126, 28.1740),
    "forest": (84.2129, 23.7380),
    "hill": (76.7904, 31.2834),
    "plain": (77.6157, 13.3143),
}

CHUNK = 1 << 20  # 1 MiB
SEARCH_INTERVAL_S = 0.35  # stay under 3 requests/s
DOWNLOAD_MIN_GAP_S = 35  # stay under 2 requests/min
WORKERS = 2  # well under the 5-concurrent-stream cap


def token_dir() -> Path:
    """Directory holding the cached JWT (mode 600 on the token file).

    Overrides, in order: ``$BHOONIDHI_TOKEN_DIR`` > ``$XDG_CONFIG_HOME``
    > ``~/.config``. Always returns ``<root>/bhoonidhi_cli``.
    """
    if os.environ.get("BHOONIDHI_TOKEN_DIR"):
        root = Path(os.environ["BHOONIDHI_TOKEN_DIR"]).expanduser()
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    return root / "bhoonidhi_cli"


def token_file() -> Path:
    return token_dir() / "bhoonidhi_token.json"


def default_out_dir() -> Path:
    """Default products directory: ``$BHOONIDHI_OUT`` > ``~/bhoonidhi_downloads``."""
    if os.environ.get("BHOONIDHI_OUT"):
        return Path(os.environ["BHOONIDHI_OUT"]).expanduser()
    return Path.home() / "bhoonidhi_downloads"
