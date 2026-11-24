"""Bhoonidhi (NRSC) data downloader — search & fetch eligible satellite products.

Talks to the official Bhoonidhi API (STAC catalogue + authenticated download):
    auth    POST https://bhoonidhi-api.nrsc.gov.in/auth/token
    search  POST https://bhoonidhi-api.nrsc.gov.in/data/search
    item    GET  https://bhoonidhi-api.nrsc.gov.in/data/collections/{col}/items/{id}
    fetch   GET  https://bhoonidhi-api.nrsc.gov.in/download?id=...&collection=...

Requires a registered Bhoonidhi account (login page:
https://bhoonidhi.nrsc.gov.in/bhoonidhi/login.html).  Credentials come from
``BHOONIDHI_USER`` / ``BHOONIDHI_PASS`` (or ``--user`` / ``--passwd``; the
password is prompted if omitted).  The JWT is cached in ``<repo>/.auth/
bhoonidhi_token.json`` (mode 600, gitignored) and refreshed automatically
when it expires.

Respects the published rate limits: search 3 r/s, download 2/min with at most
5 concurrent streams (this script uses 2 workers), HTTP 429/412 → back-off,
504 → retry.  Only ``Online = Y`` items are downloaded (per the API spec,
``N`` products must be ordered via Browse & Order anyway).  Writes
``search_results.json`` and ``manifest.json`` next to the product files.

Works with plain Python 3.10+ (stdlib only). Examples (from the repo root):
    # search every platform over the Delhi-NCR urban benchmark site
    python scripts/download_bhoonidhi.py \\
        --site delhi-urban --start 2025-01-01 --end 2025-02-28 --preview

    # search a single platform, then download every eligible product
    python scripts/download_bhoonidhi.py \\
        --platform ResourceSat-2A --site delhi-urban --start 2025-01-01 \\
        --end 2025-02-28 --download --out data/bhoonidhi
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import getpass
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://bhoonidhi-api.nrsc.gov.in"
TOKEN_URL = f"{API_BASE}/auth/token"
SEARCH_URL = f"{API_BASE}/data/search"
DOWNLOAD_URL = f"{API_BASE}/download"
AUTH_DIR = Path(__file__).resolve().parents[1] / ".auth"
TOKEN_FILE = AUTH_DIR / "bhoonidhi_token.json"

# PS-10 LISS-4 collections, still handy to pass via ``--collections``
# (the default is now every collection registered on the API).
LISS4_COLLECTIONS = [
    "ResourceSat-2_LISS4-MX70_L2",
    "ResourceSat-2A_LISS4-MX70_L2",
]
COLLECTIONS_URL = f"{API_BASE}/data/collections"

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
WORKERS = 2  # well under the 5-concurrent cap


def log(msg: str) -> None:
    print(f"[bhoonidhi] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def _request(
    url: str,
    body: dict | None = None,
    token: str | None = None,
    method: str | None = None,
    timeout: int = 60,
):
    """Return (status, headers, body-bytes) without raising on HTTP errors."""
    headers = {"Accept": "application/json", "User-Agent": "bhoonidhi-downloader/0.1"}
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


def _open_stream(url: str, token: str):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", "bhoonidhi-downloader/0.1")
    return req


# --------------------------------------------------------------------------- #
# Auth token cache
# --------------------------------------------------------------------------- #
def _jwt_exp(token: str) -> float | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (ValueError, KeyError, TypeError):
        return None


def _auth_request(user: str, body: dict) -> tuple[int, bytes]:
    status, _, raw = _request(TOKEN_URL, body=body)
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
    if TOKEN_FILE.exists():
        try:
            cached = json.loads(TOKEN_FILE.read_text())
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
    expires_at = _jwt_exp(tok["access_token"]) or (now + tok.get("expires_in", 3600))
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps(
            {
                "user": user,
                "access_token": tok["access_token"],
                "refresh_token": tok.get("refresh_token", ""),
                "expires_at": expires_at,
                "saved": datetime.now(timezone.utc).isoformat(),
            }
        )
    )
    os.chmod(TOKEN_FILE, 0o600)


def ensure_token(user: str, passwd: str | None) -> str:
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
    try:
        TOKEN_FILE.unlink()
    except FileNotFoundError:
        pass
    log("deleted cached token — next auth request will re-login")


class Session:
    """Holds the current access token and transparently re-authenticates on 401.

    The password is kept in memory only for the lifetime of this process;
    it is never written to disk.
    """

    def __init__(self, user: str, passwd: str | None = None):
        self.user = user
        self.passwd = passwd
        self.token = ensure_token(user, passwd)

    def handle_401(self) -> None:
        log("token rejected by server (HTTP 401) — re-authenticating once")
        invalidate_cache(self.user)
        self.token = ensure_token(self.user, self.passwd)


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
def polygon_around(lon: float, lat: float, radius_km: float) -> dict:
    verts = []
    dlat = math.radians(radius_km / 6371.0)
    dlon = math.radians(radius_km / 6371.0) / math.cos(math.radians(lat))
    for i in range(0, 16, 2):
        a = 2 * math.pi * i / 16
        verts.append([lon + dlon * math.cos(a), lat + dlat * math.sin(a)])
    verts.append(verts[0])
    return {"type": "Polygon", "coordinates": [verts]}


def list_collections(sess: Session) -> list[str]:
    """Fetch every STAC collection id currently registered on the API."""
    status, _, raw = _request(COLLECTIONS_URL, token=sess.token)
    if status == 401:
        sess.handle_401()
        status, _, raw = _request(COLLECTIONS_URL, token=sess.token)
    if status != 200:
        raise SystemExit(f"collection listing failed (HTTP {status}): {raw[:400]!r}")
    doc = json.loads(raw)
    return [c["id"] for c in doc.get("collections", [])]


def resolve_collections(args, sess: Session) -> list[str]:
    """Map ``--platform`` / explicit ``--collections`` to concrete collection ids.

    Explicit ``--collections`` wins if given. Otherwise ``--platform <p>``
    selects every collection whose id starts with ``p`` (case-insensitive).
    Otherwise every registered collection is searched.
    """
    if args.collections:
        return list(args.collections)
    all_ids = list_collections(sess)
    if args.platform:
        prefix = args.platform.strip().upper()
        picked = [c for c in all_ids if c.upper().startswith(prefix)]
        if not picked:
            known = sorted({c.split("_")[0] for c in all_ids})
            raise SystemExit(
                f"no collection starts with {args.platform!r}; "
                f"known prefixes: {', '.join(known)}"
            )
        log(f"--platform {args.platform}: {len(picked)} collection(s): {', '.join(picked)}")
        return picked
    log(f"searching all {len(all_ids)} collection(s) registered on the API")
    return all_ids


def build_query(args: argparse.Namespace) -> dict:
    query: dict = {
        "collections": args.collections,
        "datetime": f"{args.start}T00:00:00Z/{args.end}T23:59:59Z"
        if args.end
        else f"{args.start}T00:00:00Z/",
        "limit": args.limit,
    }
    if args.aoi_file:
        geo = json.loads(Path(args.aoi_file).read_text())
        query["intersects"] = geo.get("geometry", geo)
    elif args.site:
        lon, lat = BENCHMARK_SITES[args.site]
        log(f"benchmark site '{args.site}': lon={lon} lat={lat} r={args.radius_km} km")
        query["intersects"] = polygon_around(lon, lat, args.radius_km)
    elif args.point:
        lon, lat = (float(v) for v in args.point.split(","))
        query["intersects"] = polygon_around(lon, lat, args.radius_km)
    elif args.bbox:
        query["bbox"] = [float(v) for v in args.bbox.split(",")]

    if args.extra_filter:
        query["filter"] = json.loads(args.extra_filter)
    elif args.online_only:
        query["filter"] = {"args": [{"property": "Online"}, "Y"], "op": "eq"}
    query["filter-lang"] = "cql2-json"
    return query


def search(sess: Session, args: argparse.Namespace) -> list[dict]:
    query = build_query(args)
    items: list[dict] = []
    while True:
        time.sleep(SEARCH_INTERVAL_S)
        status, _, raw = _request(SEARCH_URL, body=query, token=sess.token)
        if status == 401:
            sess.handle_401()
            continue
        if status == 429:
            log("search rate-limited (HTTP 429); waiting 10 s")
            time.sleep(10)
            continue
        if status != 200:
            raise SystemExit(f"search failed (HTTP {status}): {raw[:400]!r}")
        doc = json.loads(raw)
        items.extend(doc.get("features", []))
        returned = doc.get("context", {}).get("returned", 0)
        log(f"search page: {returned} items (total {len(items)})")
        if returned == 0 or len(items) >= args.limit:
            break
        next_url = next(
            (l["href"] for l in doc.get("links", []) if l.get("rel") == "next"), None
        )
        if not next_url:
            break
        query = dict(query)
        query["token"] = urllib.parse.parse_qs(
            urllib.parse.urlparse(next_url).query
        ).get("token", [""])[0]
    return items


# --------------------------------------------------------------------------- #
# Item details + download
# --------------------------------------------------------------------------- #
def with_details(sess: Session, items: list[dict]) -> list[dict]:
    out = []
    for item in items:
        url = f"{API_BASE}/data/collections/{item['collection']}/items/{item['id']}"
        time.sleep(SEARCH_INTERVAL_S)
        status, _, raw = _request(url, token=sess.token)
        if status == 200:
            out.append(json.loads(raw))
        elif status == 401:
            sess.handle_401()
            time.sleep(SEARCH_INTERVAL_S)
            status, _, raw = _request(url, token=sess.token)
            if status == 200:
                out.append(json.loads(raw))
            else:
                log(
                    f"  ! item metadata HTTP {status} for {item['id']} — using search fields"
                )
                out.append(item)
        else:
            log(
                f"  ! item metadata HTTP {status} for {item['id']} — using search fields"
            )
            out.append(item)
    return out


class _RateGate:
    """Serialises the 2/min download start rate across worker threads."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_start = 0.0

    def wait(self) -> None:
        with self.lock:
            delta = time.time() - self.last_start
            if delta < DOWNLOAD_MIN_GAP_S:
                time.sleep(DOWNLOAD_MIN_GAP_S - delta)
            self.last_start = time.time()


def download_one(sess: Session, item: dict, out_dir: Path, gate: _RateGate) -> str:
    iid = item["id"]
    col = item["collection"]
    dest = out_dir / f"{col}__{iid}.zip"
    if dest.exists() and dest.stat().st_size > 0:
        return "skipped (already present)"

    url = f"{DOWNLOAD_URL}?id={urllib.parse.quote(iid)}&collection={urllib.parse.quote(col)}"
    last = "failed"
    for attempt in range(1, 6):
        gate.wait()
        try:
            req = _open_stream(url, sess.token)
            with urllib.request.urlopen(req, timeout=300) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                tmp = dest.with_suffix(dest.suffix + ".part")
                done = 0
                with open(tmp, "wb") as fh:
                    while chunk := resp.read(CHUNK):
                        fh.write(chunk)
                        done += len(chunk)
                        if total:
                            log(f"  {iid}: {done / 1e6:.0f}/{total / 1e6:.0f} MiB")
                tmp.rename(dest)
            return "ok"
        except urllib.error.HTTPError as e:
            last = f"failed (HTTP {e.code})"
            if e.code == 401:
                sess.handle_401()
                continue
            if e.code == 404:
                return "failed (404 — product not in online storage)"
            if e.code in (412, 429, 504):
                delay = 90 if e.code == 412 else 60 * attempt
                log(
                    f"  ! {iid}: HTTP {e.code} (attempt {attempt}/5); waiting {delay} s"
                )
                time.sleep(delay)
                continue
            break
        except (urllib.error.URLError, TimeoutError) as e:
            last = f"failed ({e})"
            log(f"  ! {iid}: network error (attempt {attempt}/5)")
            time.sleep(30 * attempt)
    return last


def summarize(items: list[dict]) -> None:
    if not items:
        log("no items matched the search")
        return
    dates = sorted(
        (i.get("properties", {}).get("Imaging_Date") or i.get("datetime") or "")[:10]
        for i in items
    )
    online = sum(1 for i in items if str(i.get("properties", {}).get("Online")) == "Y")
    log(
        f"summary: {len(items)} item(s) | {online} Online=Y | dates {dates[0]} … {dates[-1]}"
    )
    for i in items:
        p = i.get("properties", {})
        centre = p.get("CentreLatLon")
        centre = (
            f"({centre[0]},{centre[1]})"
            if isinstance(centre, list) and len(centre) == 2
            else "-"
        )
        log(
            f"  {i['id']}\n"
            f"    {i['collection']} | date={p.get('Imaging_Date')} | "
            f"online={p.get('Online')} | {p.get('Platform')} {p.get('Instrument')} "
            f"mode={p.get('Mode')} | path,row={p.get('Path')},{p.get('Row')} | centre={centre}"
        )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None) -> argparse.Namespace:
    default_out = Path(__file__).resolve().parents[1] / "data" / "bhoonidhi"
    ap = argparse.ArgumentParser(
        description="Search & download Bhoonidhi (NRSC) satellite products "
        "(all ISRO + NISAR + Sentinel platforms by default).",
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
        default=None,
        help="explicit STAC collection id(s); default = every collection "
        "registered on the API",
    )
    ap.add_argument(
        "--platform",
        help="search every collection starting with this platform prefix, "
        "e.g. EOS-06, ResourceSat-2A, NISAR, Sentinel-1A",
    )
    ap.add_argument(
        "--limit", type=int, default=500, help="max items returned by search (API cap 500)"
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
        "--max-downloads", type=int, default=0, help="cap on products fetched (0 = all eligible)"
    )
    ap.add_argument("--out", type=Path, default=default_out, help="output directory")
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
    args.collections = resolve_collections(args, sess)
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
    gate = _RateGate()
    log(f"downloading {len(pick)} product(s) — 2/min API limit, this may take a while")
    results: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(download_one, sess, i, out_dir, gate): i["id"] for i in pick}
        for fut in concurrent.futures.as_completed(futs):
            iid = futs[fut]
            results[iid] = fut.result()
            log(f"  finished: {iid} -> {results[iid]}")

    manifest = {
        "downloaded": datetime.now(timezone.utc).isoformat(),
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


if __name__ == "__main__":
    main()
