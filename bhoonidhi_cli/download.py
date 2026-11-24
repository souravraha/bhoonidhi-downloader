"""Product download: rate-gating, retries/back-off, resumable (skip-if-present)."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import http
from ._constants import CHUNK, DOWNLOAD_MIN_GAP_S, DOWNLOAD_URL, WORKERS
from ._log import log
from .auth import Session


class RateGate:
    """Serialises the 2/min download-start rate across worker threads."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_start = 0.0

    def wait(self) -> None:
        with self.lock:
            delta = time.time() - self.last_start
            delay = max(0.0, DOWNLOAD_MIN_GAP_S - delta)
            self.last_start = time.time() + delay
        if delay:
            time.sleep(delay)


def download_one(sess: Session, item: dict, out_dir: Path, gate: RateGate) -> str:
    """Fetch a single product into ``out_dir``; return a status string."""
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
            req = http.open_stream(url, sess.token)
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


def downloads(sess: Session, items: list[dict], out_dir: Path) -> dict[str, str]:
    """Download ``items`` concurrently (``WORKERS`` streams); return ``{id: status}``."""
    gate = RateGate()
    results: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(download_one, sess, i, out_dir, gate): i["id"] for i in items}
        for fut in concurrent.futures.as_completed(futs):
            iid = futs[fut]
            results[iid] = fut.result()
            log(f"  finished: {iid} -> {results[iid]}")
    return results
