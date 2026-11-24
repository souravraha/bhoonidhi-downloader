from __future__ import annotations

import argparse

from bhoonidhi_cli import (
    BENCHMARK_SITES,
    LISS4_COLLECTIONS,
    build_query,
    polygon_around,
)


def make_args(**kw) -> argparse.Namespace:
    """Build a parse_args-compatible Namespace with sensible defaults."""
    base = dict(
        collections=list(LISS4_COLLECTIONS),
        start="2025-01-01",
        end="2025-02-28",
        aoi_file=None,
        site=None,
        point=None,
        bbox=None,
        radius_km=25.0,
        limit=10,
        extra_filter=None,
        online_only=True,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_build_query_site_uses_benchmark_site_and_polygon():
    q = build_query(make_args(site="delhi-urban"))
    assert q["collections"] == LISS4_COLLECTIONS
    assert q["datetime"] == "2025-01-01T00:00:00Z/2025-02-28T23:59:59Z"
    assert q["limit"] == 10
    poly = q["intersects"]
    assert poly["type"] == "Polygon"
    ring = poly["coordinates"][0]
    assert ring[0] == ring[-1]  # closed ring
    lon, lat = BENCHMARK_SITES["delhi-urban"]
    xs = [v[0] for v in ring]
    ys = [v[1] for v in ring]
    # the AOI should be centred on the site
    assert abs((min(xs) + max(xs)) / 2 - lon) < 1e-6
    assert abs((min(ys) + max(ys)) / 2 - lat) < 1e-6
    assert q["filter-lang"] == "cql2-json"
    assert q["filter"] == {"args": [{"property": "Online"}, "Y"], "op": "eq"}


def test_build_query_point_radius():
    q = build_query(make_args(point="77.6,28.1"))
    poly = q["intersects"]
    assert poly["type"] == "Polygon"
    ring = poly["coordinates"][0]
    assert abs((min(v[0] for v in ring) + max(v[0] for v in ring)) / 2 - 77.6) < 1e-6
    assert abs((min(v[1] for v in ring) + max(v[1] for v in ring)) / 2 - 28.1) < 1e-6


def test_build_query_bbox_uses_bbox_not_intersects():
    q = build_query(make_args(bbox="70,20,90,35"))
    assert q["bbox"] == [70.0, 20.0, 90.0, 35.0]
    assert "intersects" not in q


def test_build_query_open_ended_datetime_when_no_end():
    q = build_query(make_args(end=None))
    assert q["datetime"] == "2025-01-01T00:00:00Z/"


def test_build_query_extra_filter_overrides_online_only():
    extra = '{"args":[{"property":"Cloud_Cover"},"80"],"op":"lt"}'
    q = build_query(make_args(extra_filter=extra, online_only=True))
    assert q["filter"] == {"args": [{"property": "Cloud_Cover"}, "80"], "op": "lt"}


def test_build_query_no_online_filter_when_disabled():
    q = build_query(make_args(site="forest", online_only=False, extra_filter=None))
    assert "no-filter-marker" not in q  # just asserts a build (no exception)
    assert q["filter-lang"] == "cql2-json"
    # with online_only off and no extra filter, no 'filter' key is set
    assert "filter" not in q


def test_polygon_around_is_closed_octagon():
    poly = polygon_around(77.6, 28.1, 25.0)
    ring = poly["coordinates"][0]
    assert len(ring) == 9  # 8 vertices + repeated first
    assert ring[0] == ring[-1]


def test_aoi_file_geometry_used(monkeypatch, tmp_path):
    import json

    geo_json = tmp_path / "aoi.geojson"
    geom = {"type": "Point", "coordinates": [77.0, 20.0]}
    geo_json.write_text(
        json.dumps({"type": "Feature", "geometry": geom, "properties": {}})
    )
    q = build_query(make_args(aoi_file=str(geo_json)))
    assert q["intersects"] == geom
