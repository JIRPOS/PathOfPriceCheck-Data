"""poewiki cargo tables — which modifiers each unique item can roll.

This is the one thing in the bundle that does not come from the game or from GGG's API,
because neither has it. Mod-to-unique assignment is server-side: verified against patch
3.29.1.2.2 by walking all 1,205,200 paths in the bundle index, the only per-unique tables the
client ships are ``UniqueStashLayout``, ``UniqueMaps``, ``UniqueJewelLimits`` and
``UniqueUpgradesClient`` — names, art, stash placement and limits. ``Mods.dat`` does carry
every unique-generation mod with its stats and ranges; only the grouping under an item is
missing.

So this source supplies an **id → id edge list and nothing else**: unique page name → the
GGG mod ids it can roll, plus the wiki's own `is_random` / `is_implicit` flags and the
placeholder text it renders for a pool ("<Two Random Herald of Ash modifier>"). Every number
in the emitted dataset still comes from the client. That matters for licensing as much as for
correctness — see DATA-LICENSE.md.

The wiki sits behind a bot challenge that answers HTML instead of JSON when it triggers, so
a fetch failure is expected to happen eventually and ``cache_path`` exists to survive it.
"""

from __future__ import annotations

import html
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://www.poewiki.net/index.php"

# Attribution requirement, not politeness: the wiki is CC BY-NC 3.0.
ATTRIBUTION = "poewiki.net, CC BY-NC 3.0"

USER_AGENT = (
    "PathOfPriceCheck-Data-builder/1.0 "
    "(+https://github.com/JIRPOS/PathOfPriceCheck-Data)"
)

# Cargo caps a single export well below the row count we need, so this pages. `order_by` is
# not cosmetic: without a total order the offsets can shift under us between requests and a
# row is silently skipped or repeated.
PAGE_SIZE = 500
MAX_PAGES = 200
PAGE_DELAY_S = 0.5

FIELDS = (
    "items.name=name,"
    "items.base_item=base,"
    "item_mods.id=mod,"
    "item_mods.is_random=rnd,"
    "item_mods.is_implicit=impl,"
    "item_mods.text=hint"
)

QUERY = {
    "title": "Special:CargoExport",
    "tables": "items,item_mods",
    "join_on": "items._pageID=item_mods._pageID",
    "fields": FIELDS,
    "where": 'items.rarity="Unique"',
    "order_by": "items.name,item_mods.id,item_mods.text",
    "format": "json",
}


class WikiError(RuntimeError):
    pass


def _get(offset: int, timeout: int) -> list[dict]:
    params = dict(QUERY, limit=str(PAGE_SIZE), offset=str(offset))
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as e:
        # The bot challenge answers 200 with an HTML interstitial, so a parse failure here
        # means "we were challenged", not "the data is malformed".
        head = raw[:200].decode("utf-8", "replace").replace("\n", " ")
        raise WikiError(f"non-JSON response at offset {offset} "
                        f"(bot challenge?): {head}") from e
    if not isinstance(rows, list):
        raise WikiError(f"expected a JSON array at offset {offset}, got {type(rows).__name__}")
    return rows


def unescape(s: str) -> str:
    """Undo cargo's HTML escaping, which is applied twice.

    Load-bearing on both sides: ``Abberath&#039;s Hooves`` is not an item name and
    ``Cassia&#039;s Pride`` is not a mod id — the one row that failed to join into
    ``Mods.dat`` during validation failed for exactly that. Pool placeholders come back
    doubly escaped (``&amp;lt;Two or Three...``), so one pass is not enough. Two passes and no
    more: a loop to fixpoint would eat a literal ``&amp;`` out of real text.
    """
    return html.unescape(html.unescape(s)).strip()


def clean(rows: list[dict]) -> list[dict]:
    return [{k: unescape(v) if isinstance(v, str) else v for k, v in r.items()} for r in rows]


def load_cache(path: Path) -> list[dict]:
    """The cached rows, cleaned. The cache holds what the wiki sent, verbatim.

    Deliberately raw on disk: cleaning is our interpretation of their markup and it will be
    wrong again, and re-deriving it from the cache beats needing a fresh fetch to fix it.
    """
    return clean(json.loads(path.read_text(encoding="utf-8")))


def fetch(cache_path: Path | None = None, allow_cache_fallback: bool = False,
          timeout: int = 60, retries: int = 3) -> tuple[list[dict], bool]:
    """Every (unique, mod) row the wiki publishes. Returns ``(rows, from_cache)``.

    A successful fetch refreshes ``cache_path``. With ``allow_cache_fallback`` a failed one
    falls back to it, which is how a bot challenge degrades to a stale mapping instead of
    taking the whole bundle down — the rest of the bundle has nothing to do with the wiki.
    """
    try:
        rows: list[dict] = []
        for page in range(MAX_PAGES):
            last: Exception | None = None
            for attempt in range(retries):
                try:
                    got = _get(page * PAGE_SIZE, timeout)
                    last = None
                    break
                except Exception as e:  # noqa: BLE001 - retry everything, then report
                    last = e
                    if attempt + 1 < retries:
                        time.sleep(2 ** attempt)
            if last is not None:
                raise WikiError(f"page {page} failed after {retries} attempts: {last}")
            rows.extend(got)
            if len(got) < PAGE_SIZE:
                break
            time.sleep(PAGE_DELAY_S)
        else:
            raise WikiError(f"still paging after {MAX_PAGES} pages ({len(rows)} rows); "
                            "the query is probably not terminating")
        if not rows:
            raise WikiError("query returned no rows")
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return clean(rows), False
    except Exception as e:  # noqa: BLE001
        if not (allow_cache_fallback and cache_path and cache_path.exists()):
            raise
        print(f"  WARNING: poewiki fetch failed ({e})")
        print(f"  falling back to the cached mapping in {cache_path}")
        return load_cache(cache_path), True
