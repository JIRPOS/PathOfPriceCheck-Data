import json

from ppcdata.emit import items as emit_items
from ppcdata.sources import exchange


def _digest(*pairs) -> dict:
    return {"next_change_id": 1, "markets": [{"market_pair": list(p)} for p in pairs]}


def test_both_sides_of_a_market_count():
    # A market is evidence that each of the two items trades, not just the one being asked
    # about. The feed names no items any other way, so the pair is the whole of the record.
    ids = exchange._ids(_digest(("A", "B"), ("A", "C")))
    assert ids == {"A", "B", "C"}


def test_a_published_but_empty_hour_reads_as_unpublished():
    # The hour in progress answers 404 with this body; an hour that ended but is a few minutes
    # late answers the same. Neither is "nothing traded", and treating it as an answer would
    # let the cursor walk past an hour that publishes a moment later.
    assert exchange._ids(_digest()) is None


def test_latest_hour_is_the_one_that_just_ended():
    # The hour in progress does not exist yet — measured: 404 with a well-formed empty digest.
    assert exchange.latest_hour(1722031500) == 1722027600
    # Exactly on the boundary, the hour that just closed is the newest there can be.
    assert exchange.latest_hour(1722031200) == 1722027600


def _crawler(published: dict[int, set[str]], newest: int):
    """A fetch_hour stand-in over a fixed history, plus the hours it was asked for."""
    asked: list[int] = []

    def fetch(hour, **kw):
        asked.append(hour)
        if hour > newest:
            raise AssertionError(f"asked for {hour}, past the newest published hour")
        return published.get(hour)

    return fetch, asked


def test_the_cursor_resumes_where_it_stopped(tmp_path, monkeypatch):
    state = tmp_path / "exchange-seen.json"
    h = 1722027600
    published = {h: {"A"}, h + 3600: {"B"}, h + 7200: {"C"}}
    newest = h + 7200

    fetch, asked = _crawler(published, newest)
    monkeypatch.setattr(exchange, "fetch_hour", fetch)
    monkeypatch.setattr(exchange, "latest_hour", lambda *a: h + 3600)
    st = exchange.crawl(state, backfill_from=h, delay=0)
    assert st["hours_crawled"] == 2
    assert set(json.loads(state.read_text())["ids"]) == {"A", "B"}

    # A second run picks up at the next hour and re-reads none of the first run's.
    asked.clear()
    monkeypatch.setattr(exchange, "latest_hour", lambda *a: newest)
    st = exchange.crawl(state, delay=0)
    assert asked == [h + 7200]
    assert st["exchange_ids_added"] == 1
    assert set(json.loads(state.read_text())["ids"]) == {"A", "B", "C"}


def test_a_recent_unpublished_hour_stops_the_crawl_rather_than_being_skipped(
        tmp_path, monkeypatch):
    # The feed runs a few minutes late often enough to matter. Advancing past an hour that
    # publishes a moment later would lose it permanently, because nothing ever re-walks.
    state = tmp_path / "s.json"
    h = 1722027600
    newest = h + 3600 * 3
    fetch, asked = _crawler({h: {"A"}}, newest)
    monkeypatch.setattr(exchange, "fetch_hour", fetch)
    monkeypatch.setattr(exchange, "latest_hour", lambda *a: newest)

    st = exchange.crawl(state, backfill_from=h, delay=0)
    assert st["hours_crawled"] == 1
    assert st["last_hour"] == h
    assert asked == [h, h + 3600]  # stopped at the gap, did not walk to the end


def test_an_old_unpublished_hour_is_a_real_gap_and_is_stepped_over(tmp_path, monkeypatch):
    # The other half of the same rule: an hour still empty long after it ended is one GGG never
    # published, and waiting for it would stall the crawl forever. So the walk steps over the
    # old gaps to reach the published hour behind them, and still stops at the grace boundary —
    # both halves in one history, because it is the boundary between them that is the rule.
    state = tmp_path / "s.json"
    h = 1722027600
    newest = h + 3600 * 20
    fetch, _ = _crawler({h: {"A"}, h + 3600 * 10: {"B"}}, newest)
    monkeypatch.setattr(exchange, "fetch_hour", fetch)
    monkeypatch.setattr(exchange, "latest_hour", lambda *a: newest)

    st = exchange.crawl(state, backfill_from=h, delay=0)
    assert set(json.loads(state.read_text())["ids"]) == {"A", "B"}
    assert st["hours_unpublished"] == 13  # h+1h..h+9h and h+11h..h+14h
    # The last hour outside the grace window. h+15h onwards may yet publish, so the cursor
    # waits for them rather than writing them off.
    assert st["last_hour"] == h + 3600 * 14


def test_a_failed_request_stops_without_advancing_past_the_hour(tmp_path, monkeypatch):
    # An hour we never actually read must not be counted as read: the cursor only ever moves
    # over hours whose contents are in the set.
    state = tmp_path / "s.json"
    h = 1722027600

    def fetch(hour, **kw):
        if hour == h:
            return {"A"}
        raise exchange.ExchangeError("boom")

    monkeypatch.setattr(exchange, "fetch_hour", fetch)
    monkeypatch.setattr(exchange, "latest_hour", lambda *a: h + 3600 * 5)
    st = exchange.crawl(state, backfill_from=h, delay=0)
    assert st["last_hour"] == h
    assert st["error"]
    # And the ids read before the failure are kept, not thrown away with the run.
    assert set(json.loads(state.read_text())["ids"]) == {"A"}


# --- the emitted flag ------------------------------------------------------------------

TRADED = "Metadata/Items/Currency/CurrencyRerollRare"
NOT_TRADED = "Metadata/Items/Armours/Gloves/Gloves1"


def _items():
    return {"result": [{"id": "", "entries": [
        {"name": "Chaos Orb", "type": "Chaos Orb"},
        {"name": "Iron Gauntlets", "type": "Iron Gauntlets"},
    ]}]}


def _bases():
    return [{"_index": 1, "Name": "Chaos Orb", "Id": TRADED, "ModDomain": 43,
             "ItemClassesKey": 38},
            {"_index": 2, "Name": "Iron Gauntlets", "Id": NOT_TRADED, "ModDomain": 1,
             "ItemClassesKey": 38}]


def test_only_an_item_the_feed_has_named_is_flagged():
    records, stats = emit_items.build(_items(), _bases(), [], [], [], {TRADED})
    by_name = {r["name"]: r for r in records}
    assert by_name["Chaos Orb"]["exchange"] is True
    # Absent rather than false: the client reads a missing flag as "does not trade", and the
    # bundle-level `source.exchange_items` is what says the flags are there to be read at all.
    assert "exchange" not in by_name["Iron Gauntlets"]
    assert stats["traded_on_currency_exchange"] == 1


def test_no_crawl_flags_nothing():
    # An absent state file must produce exactly the shape of a bundle published before this
    # dataset existed, or a client would read "no flag" as "does not trade" on every item.
    records, stats = emit_items.build(_items(), _bases(), [], [], [])
    assert not any("exchange" in r for r in records)
    assert stats["traded_on_currency_exchange"] == 0


def test_an_id_the_feed_names_but_no_base_carries_is_reported():
    # Expected to be small and non-zero — the feed covers leagues and items trade does not
    # list — so it is reported rather than asserted on. A number that jumps says the join drifted.
    _, stats = emit_items.build(_items(), _bases(), [], [], [], {TRADED, "Metadata/Items/Nope"})
    assert stats["_exchange_ids_unmatched"] == ["Metadata/Items/Nope"]
