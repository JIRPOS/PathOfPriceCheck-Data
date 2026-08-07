"""GGG's in-game currency-exchange feed — which items have ever traded on it.

The app prices a stack of currency, a scarab, an essence or a divination card off this feed
rather than off the trade site, because an exchange market is not a listing and the trade site
has nothing to say about any of them. It reads **one hourly digest**, the hour that just ended.
That is the right price when there is one, and it cannot answer the question underneath it:
an item with no market in that hour is indistinguishable from an item that does not trade on
the exchange at all. For a thin item — a Weeping Essence of Greed — no trades in a given hour
is the *normal* case, and poe.ninja has no price for one either, so the check comes back saying
nothing whatsoever.

So this source answers the standing question instead of the hourly one: **has this item ever
appeared in an exchange market?** That is a property of the item, not of the hour, so it
belongs in the bundle rather than in the live feed, and it makes the app able to say "trades on
the currency exchange — no trades in the past hour", which is a real answer.

The endpoint (https://web.poecdn.com/api/currency-exchange/<unix-hour>, documented at
https://www.pathofexile.com/developer/docs/reference) is public, unauthenticated, and on the
CDN rather than on the API host — so no rate-limit policy, no registered application. Four
measured facts shape the crawl:

* **Any hour can be addressed directly.** Walking ``next_change_id`` is not required, so this
  is a forward scan over a cursor rather than a linked list that must be replayed.
* **A published hour never changes** — every digest answers ``cache-control: max-age≈31,500,000``
  (one year). Nothing ever needs re-fetching, which is what makes a committed cursor sound.
* **The hour in progress does not exist**: it answers 404 with a well-formed
  ``{"next_change_id":…,"markets":[]}``. The feed also publishes a few minutes late often
  enough to matter, so a recent empty hour means "not yet", not "nothing traded".
* **gzip is worth asking for.** Measured on the hour ending 2026-08-07T10:00Z: 2,054,199 bytes
  of JSON in 128,505 bytes on the wire, a 16× saving. Over the 17.8k-hour backfill that is the
  difference between ~17 GB and ~2.3 GB.
* **The TLS handshake, not the payload, is what a crawl of this shape costs.** Measured over
  ten mid-history hours: 1.29 s each on a fresh connection per request against 0.09 s over one
  held open — a 14× difference, and the whole of it is the handshake (of that 0.09 s, 0.086 is
  the transfer, 0.006 the gunzip and the JSON parse together). It is the difference between a
  6.4-hour backfill and a half-hour one, so the connection is held rather than reopened.

The payload carries **no item names at all** — every side of every market is a
``Metadata/Items/...`` path — which is the same reason ``emit/items.py`` emits ``metadataId``.
Both sides of a pair count: a market is evidence that each of the two items trades.

One hour holds 40+ leagues including private ones, and the dataset is the union over all of
them. "Can this item be exchanged" is a fact about the item; which league someone traded it in
is not.
"""

from __future__ import annotations

import gzip
import http.client
import json
import time
from pathlib import Path

HOST = "web.poecdn.com"
PATH = "/api/currency-exchange"
ENDPOINT = f"https://{HOST}{PATH}"

# The first hour the feed serves — Settlers launch. Asking for anything earlier, or omitting
# the id entirely, answers this hour rather than an error.
FIRST_HOUR = 1722027600

HOUR = 3600

USER_AGENT = (
    "PathOfPriceCheck-Data-builder/1.0 "
    "(+https://github.com/JIRPOS/PathOfPriceCheck-Data)"
)

# How long an hour may stay unpublished before the crawl treats it as a genuine gap in GGG's
# history and steps over it. Below this the cursor stops instead, so a run a few minutes ahead
# of the feed resumes at the same hour rather than skipping it forever — the difference between
# "not yet" and "never", which the payload itself does not state.
GAP_GRACE_HOURS = 6

# Write the cursor back this often during a long crawl. The backfill is ~17.8k requests and
# will be interrupted; the cost of a checkpoint is a 100 KB file rewrite, so this is cheap
# insurance against re-walking hours already counted.
CHECKPOINT_EVERY = 250

# Requests to serve on one connection before retiring it, and how long to wait on one that has
# gone quiet. See `Session` for the measurement behind both: a mute keep-alive connection is
# what a long crawl actually fails as, and only the timeout notices it.
MAX_PER_CONNECTION = 100
TIMEOUT_S = 30


class ExchangeError(RuntimeError):
    pass


def latest_hour(now_s: int | None = None) -> int:
    """The newest hour that can be published: the last one to have fully elapsed."""
    now = int(time.time()) if now_s is None else int(now_s)
    return now // HOUR * HOUR - HOUR


def url(hour: int) -> str:
    return f"{ENDPOINT}/{int(hour)}"


class Session:
    """One HTTPS connection, held open across hours and recycled before it goes stale.

    Not an optimisation detail: reopening it per request is 93% of the crawl's wall time (see
    the module docstring). The server may close a keep-alive connection whenever it likes, so
    a dropped connection is a reconnect rather than an error — that is what separates
    ``_once`` from the retry loop around it.

    **The connection is retired after ``MAX_PER_CONNECTION`` requests, and that is not
    housekeeping.** Measured: a backfill ran 250 hours in 90 s and then hung outright, with the
    socket still ``ESTAB`` and nothing queued on it, while a *fresh* connection to the same host
    answered the same request in 0.2 s. The CDN goes mute on a long-lived connection rather than
    closing it, so nothing raises and only the timeout notices — the one failure keep-alive buys.
    Retiring it first costs a handshake every hundred hours (~1% of the crawl) and removes the
    stall entirely.
    """

    def __init__(self, timeout: int = TIMEOUT_S):
        self.timeout = timeout
        self._conn: http.client.HTTPSConnection | None = None
        self._served = 0

    def _connect(self) -> http.client.HTTPSConnection:
        if self._conn is not None and self._served >= MAX_PER_CONNECTION:
            self.close()
        if self._conn is None:
            self._conn = http.client.HTTPSConnection(HOST, timeout=self.timeout)
            self._served = 0
        self._served += 1
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self._served = 0

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _once(self, hour: int) -> tuple[int, bytes]:
        conn = self._connect()
        conn.request("GET", f"{PATH}/{int(hour)}",
                     headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                              "Accept-Encoding": "gzip", "Connection": "keep-alive"})
        r = conn.getresponse()
        raw = r.read()  # always drained, or the connection cannot be reused
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return r.status, raw

    def fetch(self, hour: int, retries: int = 3) -> set[str] | None:
        """Every metadata id named by any market in this hour, or ``None`` if unpublished.

        ``None`` is not a failure: it is what the hour in progress, and one that has ended but
        whose digest is a few minutes late, both answer — a 404 whose body is a well-formed
        empty digest rather than an error page. A published hour with markets in no league we
        care about is still a published hour; this takes the union over every league, so that
        case does not arise.

        Raises ``ExchangeError`` when the request itself fails, which the caller must treat as
        "stop here and resume later" rather than as an empty hour: advancing the cursor past
        an hour we never actually read would lose it permanently.
        """
        last: Exception | None = None
        for attempt in range(retries):
            try:
                status, raw = self._once(hour)
                if status == 404:
                    return None
                if status != 200:
                    raise ExchangeError(f"HTTP {status}")
                return _ids(json.loads(raw))
            except Exception as e:  # noqa: BLE001 - retry everything, then report
                last = e
                self.close()  # a reused connection that failed is not reusable
                if attempt + 1 < retries:
                    time.sleep(2 ** attempt)
        raise ExchangeError(f"GET {url(hour)} failed after {retries} attempts: {last}")


def fetch_hour(hour: int, session: Session | None = None, retries: int = 3) -> set[str] | None:
    """One hour, on `session` if given and on a connection of its own if not."""
    if session is not None:
        return session.fetch(hour, retries)
    with Session() as s:
        return s.fetch(hour, retries)


def _ids(payload: dict) -> set[str] | None:
    markets = payload.get("markets")
    if not isinstance(markets, list):
        raise ExchangeError("digest carries no 'markets' array")
    if not markets:
        return None  # published-but-empty is the same statement as a 404 here
    out: set[str] = set()
    for m in markets:
        pair = m.get("market_pair")
        if isinstance(pair, list):
            out.update(x for x in pair if isinstance(x, str) and x)
    return out


def load_state(path: Path) -> dict:
    """The committed cursor and id set, or an empty one.

    Committed to the repo rather than cached: an Actions cache is evictable, and a silent
    eviction here would restart the crawl from launch — 17.8k requests inside a CI job that
    budgets for six. The diff is also the review surface, showing which items newly started
    trading.
    """
    if not path.exists():
        return {"last_hour": 0, "ids": []}
    state = json.loads(path.read_text(encoding="utf-8"))
    return {"last_hour": int(state.get("last_hour", 0)),
            "ids": list(state.get("ids", []))}


def save_state(path: Path, last_hour: int, ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_hour": int(last_hour), "ids": sorted(ids)},
                               indent=1) + "\n", encoding="utf-8")


def crawl(path: Path, *, backfill_from: int | None = None, until: int | None = None,
          delay: float = 0.1, checkpoint: int = CHECKPOINT_EVERY,
          progress: bool = False) -> dict:
    """Advance the cursor to the newest published hour, unioning ids as it goes.

    Resumable by construction: the cursor is only ever advanced past an hour that was actually
    read, and it is checkpointed to disk during the walk. An interrupted backfill costs the
    hours since the last checkpoint and nothing else.

    Returns build stats. Never raises for a feed outage — the cursor simply does not advance,
    the previous flags keep serving, and the bundle still publishes. That is the
    ``--allow-stale-wiki`` precedent: a source being down costs that source its freshness, not
    the whole build.
    """
    state = load_state(path)
    ids: set[str] = set(state["ids"])
    before = len(ids)

    start = state["last_hour"] + HOUR if state["last_hour"] else None
    if start is None:
        start = backfill_from if backfill_from is not None else latest_hour() - HOUR
    elif backfill_from is not None and backfill_from < start:
        start = backfill_from  # an explicit backfill may re-walk history already crawled

    newest = latest_hour() if until is None else int(until)
    cursor = state["last_hour"]
    hours = empty = 0
    error = ""

    hour = start - start % HOUR
    session = Session()
    while hour <= newest:
        try:
            got = fetch_hour(hour, session=session)
        except ExchangeError as e:
            # Stop, do not skip. The next run resumes at this hour.
            error = str(e)
            break

        if got is None:
            # Unpublished. Recent means "not yet" and the cursor must wait for it; old enough
            # means GGG never published that hour, and waiting for it would stall the crawl
            # forever.
            if hour > newest - GAP_GRACE_HOURS * HOUR:
                break
            empty += 1
        else:
            ids |= got
        hours += 1
        cursor = hour
        hour += HOUR

        if checkpoint and hours % checkpoint == 0:
            save_state(path, cursor, ids)
            if progress:
                done = (cursor - start) // HOUR + 1
                total = (newest - start) // HOUR + 1
                print(f"  {done}/{total} hours, {len(ids)} ids "
                      f"({100.0 * done / max(total, 1):.1f}%)", flush=True)
        if delay:
            time.sleep(delay)
    session.close()

    if cursor > state["last_hour"] or ids != set(state["ids"]):
        save_state(path, cursor, ids)

    return {"hours_crawled": hours, "hours_unpublished": empty, "last_hour": cursor,
            "exchange_ids": len(ids), "exchange_ids_added": len(ids) - before,
            "error": error}


def seen_ids(path: Path) -> set[str]:
    """The id set as the emitter wants it. An absent state file is an empty set, and then
    no record carries the flag at all — which is exactly the shape of a bundle published
    before this dataset existed, and what the client's ``has_exchange_flags()`` reads."""
    return set(load_state(path)["ids"])
