"""Command-line interface for bhoonidhi-cli.

This is the ``main`` entry point wired to the ``bhoonidhi`` console script and
to ``python -m bhoonidhi_cli``.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path

from ._constants import BENCHMARK_SITES, LISS4_COLLECTIONS, default_out_dir
from ._log import log
from .api import search, summarize, with_details
from .auth import Session, invalidate_cache
from .download import downloads


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Search & download Bhoonidhi (NRSC) satellite products (LISS-4).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--user",
        default=os.environ.get("BHOONIDHI_USER"),
        help="Bhoonidhi userId ($BHOONIDHI_USER)",
    )
    ap.add_argument(
        "--passwd",
        default=os.environ.get("BHOONIDHI_PASS"),
        help="Bhoonidhi password ($BHOONIDHI_PASS); prompted if omitted",
    )
    ap.add_argument(
        "--site",
        choices=sorted(BENCHMARK_SITES),
        help="PS-10 benchmark site (§6.i terrains)",
    )
    ap.add_argument("--point", help="AOI centre as 'lon,lat'")
    ap.add_argument("--radius-km", type=float, default=25.0)
    ap.add_argument("--aoi-file", help="GeoJSON file whose geometry bounds the search")
    ap.add_argument("--bbox", help="'west,south,east,north'")
    ap.add_argument("--start", required=True, help="start date YYYY-MM-DD")
    ap.add_argument("--end", help="end date YYYY-MM-DD (default: open-ended)")
    ap.add_argument(
        "--collections",
        nargs="+",
        default=LISS4_COLLECTIONS,
        help="STAC collection id(s)",
    )
    ap.add_argument(
        "--limit", type=int, default=10, help="max items to return (API cap 500)"
    )
    ap.add_argument(
        "--online-only",
        action="store_true",
        default=True,
        help="only Online=Y items (default; N items need Browse & Order)",
    )
    ap.add_argument("--no-online-filter", dest="online_only", action="store_false")
    ap.add_argument(
        "--extra-filter",
        help='raw CQL2-JSON, e.g. \'{"args":[{"property":"Cloud_Cover"},"80"],"op":"lt"}\'',
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--preview", action="store_true", help="search + list only (no download)"
    )
    group.add_argument(
        "--download", action="store_true", help="search, then download matched products"
    )
    ap.add_argument(
        "--max-downloads", type=int, default=4, help="cap on products fetched"
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=default_out_dir(),
        help="output directory ($BHOONIDHI_OUT or ~/bhoonidhi_downloads)",
    )
    ap.add_argument(
        "--reauth",
        action="store_true",
        help="discard the cached token and force a fresh password login",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    has_aoi = args.site or args.point or args.aoi_file or args.bbox
    if not has_aoi:
        raise SystemExit("one of --site / --point / --aoi-file / --bbox is required")
    if not args.user:
        raise SystemExit(
            "provide --user (or $BHOONIDHI_USER) — a Bhoonidhi account is required"
        )

    if args.reauth:
        invalidate_cache(args.user)
    sess = Session(args.user, args.passwd)
    items = with_details(sess, search(sess, args))
    summarize(items)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "search_results.json").write_text(json.dumps(items, indent=2))

    if args.preview:
        log(f"results written to {out_dir / 'search_results.json'}")
        return

    pick = items[: args.max_downloads] if args.max_downloads > 0 else items
    if not pick:
        return
    log(f"downloading {len(pick)} product(s) — 2/min API limit, this may take a while")
    results = downloads(sess, pick, out_dir)

    manifest = {
        "downloaded": datetime.now(UTC).isoformat(),
        "results": results,
        "items": [{"id": i["id"], "collection": i["collection"]} for i in pick],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    ok = sum(1 for v in results.values() if v in ("ok", "skipped (already present)"))
    log(f"done: {ok}/{len(pick)} product(s) in {out_dir}")
    if ok < len(pick):
        log(
            "failed items: "
            + "; ".join(
                f"{k} ({v})"
                for k, v in results.items()
                if v not in ("ok", "skipped (already present)")
            )
        )
