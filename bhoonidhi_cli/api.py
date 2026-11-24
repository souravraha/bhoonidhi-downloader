"""STAC search: AOI handling, query construction, paging, item detail, summary."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
import urllib.parse

from . import http
from ._constants import API_BASE, BENCHMARK_SITES, SEARCH_INTERVAL_S, SEARCH_URL
from ._log import log
from .auth import Session


def polygon_around(lon: float, lat: float, radius_km: float) -> dict:
    """A coarse 8-sided polygon bounding a circle of ``radius_km`` about a point."""
    verts = []
    dlat = math.radians(radius_km / 6371.0)
    dlon = math.radians(radius_km / 6371.0) / math.cos(math.radians(lat))
    for i in range(0, 16, 2):
        a = 2 * math.pi * i / 16
        verts.append([lon + dlon * math.cos(a), lat + dlat * math.sin(a)])
    verts.append(verts[0])
    return {"type": "Polygon", "coordinates": [verts]}


def build_query(args: argparse.Namespace) -> dict:
    """Assemble the Bhoonidhi STAC-search body from CLI arguments."""
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
    """Run the STAC search, following ``next`` links until the limit is met."""
    query = build_query(args)
    items: list[dict] = []
    while True:
        time.sleep(SEARCH_INTERVAL_S)
        status, _, raw = http.request(SEARCH_URL, body=query, token=sess.token)
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
            (
                link["href"]
                for link in doc.get("links", [])
                if link.get("rel") == "next"
            ),
            None,
        )
        if not next_url:
            break
        query = dict(query)
        query["token"] = urllib.parse.parse_qs(
            urllib.parse.urlparse(next_url).query
        ).get("token", [""])[0]
    return items


def with_details(sess: Session, items: list[dict]) -> list[dict]:
    """Fetch full item metadata for each search hit (falling back to the hit)."""
    out = []
    for item in items:
        url = f"{API_BASE}/data/collections/{item['collection']}/items/{item['id']}"
        time.sleep(SEARCH_INTERVAL_S)
        status, _, raw = http.request(url, token=sess.token)
        if status == 200:
            out.append(json.loads(raw))
        elif status == 401:
            sess.handle_401()
            time.sleep(SEARCH_INTERVAL_S)
            status, _, raw = http.request(url, token=sess.token)
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


def summarize(items: list[dict]) -> None:
    """Human-readable one-line-per-item overview of the search results."""
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
