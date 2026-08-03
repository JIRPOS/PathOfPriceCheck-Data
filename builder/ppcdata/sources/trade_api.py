"""GGG trade API static data.

These endpoints are plain CDN reads: no auth, no rate-limit headers. A descriptive
User-Agent is mandatory — an empty one is a hard 403 from their edge.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request

BASE = "https://www.pathofexile.com/api/trade/data"
ENDPOINTS = ("stats", "items", "static", "filters")

USER_AGENT = (
    "PathOfPriceCheck-Data-builder/1.0 "
    "(+https://github.com/JIRPOS/PathOfPriceCheck-Data)"
)


class FetchError(RuntimeError):
    pass


def fetch(endpoint: str, retries: int = 3, timeout: int = 60) -> tuple[dict, str]:
    """Return ``(payload, last_modified)``. Raises FetchError after exhausting retries.

    Failing loudly is deliberate: a partial bundle must never be published, and the
    previous release keeps serving while the build is red.
    """
    url = f"{BASE}/{endpoint}"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                              "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw), r.headers.get("Last-Modified", "")
        except Exception as e:  # noqa: BLE001 - retry everything, then report
            last = e
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise FetchError(f"GET {url} failed after {retries} attempts: {last}")


def fetch_all() -> dict[str, tuple[dict, str]]:
    return {ep: fetch(ep) for ep in ENDPOINTS}


def stat_entries(stats: dict) -> list[dict]:
    """Flatten ``{result:[{id,label,entries}]}`` into entries carrying their group id."""
    out = []
    for group in stats.get("result", []):
        gid = group.get("id", "")
        for e in group.get("entries", []):
            e = dict(e)
            e["_group"] = gid
            out.append(e)
    return out


def item_entries(items: dict) -> list[dict]:
    out = []
    for group in items.get("result", []):
        gid = group.get("id", "")
        for e in group.get("entries", []):
            e = dict(e)
            e["_group"] = gid
            out.append(e)
    return out
