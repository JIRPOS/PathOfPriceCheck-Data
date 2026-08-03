"""Current PoE patch version, as published by poe-tool-dev/latest-patch-version."""

from __future__ import annotations

import urllib.request

LATEST_URL = (
    "https://raw.githubusercontent.com/poe-tool-dev/latest-patch-version/main/latest.txt"
)


def latest(timeout: int = 30) -> str:
    with urllib.request.urlopen(LATEST_URL, timeout=timeout) as r:
        return r.read().decode("utf-8").strip()
