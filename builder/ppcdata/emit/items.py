"""items.ndjson — base types, uniques, gems and cards.

The trade API's ``data/items`` is the primary source, because a name that came from there is
queryable by construction: it already carries the ``disc`` discriminators the trade site
needs to tell the three Two-Stone Rings apart. Game data then enriches the plain bases with
what trade omits — inventory size, drop level, item class and armour ranges.
"""

from __future__ import annotations

from ..sources.trade_api import item_entries

# Trade's group ids map onto our record namespaces.
_NAMESPACE_BY_GROUP = {
    "card": "DIVINATION_CARD",
    "monster": "CAPTURED_BEAST",
    "gem": "GEM",
}


def _namespace(entry: dict) -> str:
    if entry.get("flags", {}).get("unique"):
        return "UNIQUE"
    return _NAMESPACE_BY_GROUP.get(entry.get("_group", ""), "ITEM")


# The mod domain every stackable currency-like base sits in. All 978 metadata ids in one
# captured hour of the currency-exchange feed are rows in this domain, which is what makes it
# usable as a liveness signal rather than a guess.
_STACKABLE_DOMAIN = 43

# `AREA` — the pool everything that opens in the map device rolls from.
_MAP_DEVICE_DOMAIN = 5

# GGG's stand-in rows, so the trade site can list a category it has no single base for: one
# "Map" for all 491 of them, one "Blueprint", one contract per job. They are not items anybody
# holds, and their `ModDomain` describes nothing — all 21 sit in 43 with the stackable
# currency, which for a map is the pool of a different game entirely.
_TRADE_PROXY = "Metadata/Items/TradeProxy/"


def _liveness(row: dict) -> tuple[bool, bool, bool]:
    """How likely a BaseItemTypes row is the base that actually drops today, highest first.

    GGG keeps the superseded row when a base is replaced, so several rows share one display
    name: Sacrifice at Dawn is both ``VaalFragment1_2`` and, since fragments became stackable,
    ``CurrencyVaalFragment1_2``. Only the live row's id is ever named by the currency-exchange
    feed, so taking whichever came first emitted an id nothing trades under and left every
    fragment, breachstone and resonator with no exchange price at all.

    Three signals, because none covers everything, in the order they outrank each other:

    * **The map device beats the quest item.** Thirteen names have a row in both domain 5 and
      domain 43 — every Maven's Invitation and the four Eldritch ones — and the domain-5 row is
      the one the clipboard prints, as ``Item Class: Misc Map Items`` rather than
      ``Quest Items``. Without this the stackable rule below picks the quest row, and the record
      then carries the wrong item class, the wrong metadata id and the wrong mod domain: an
      invitation would be told it rolls from the pool of a quest item.
    * **The stackable domain**, which is what tells the live fragment rows from the legacy ones
      (those are in 14, not 43).
    * **The ``Currency``/``Stackable`` marker** GGG names a replacement with, which is all that
      separates the resonators and the Atlas echoes, whose rows are both in the stackable
      domain.

    Rows that tie keep the table's own order.
    """
    last = row.get("Id", "").rsplit("/", 1)[-1]
    return (row.get("ModDomain") == _MAP_DEVICE_DOMAIN,
            row.get("ModDomain") == _STACKABLE_DOMAIN,
            last.startswith("Currency") or "Stackable" in last)


def unique_art(stash_layout: list[dict], words: list[dict],
               visuals: list[dict]) -> dict[str, str]:
    """Unique display name -> the artwork's path on GGG's CDN, ``Art/2DItems/....png``.

    A unique has no row of its own in ``BaseItemTypes``: it is a name, a base and a mod list
    put together when the item drops. The one place the game states *which picture* goes with
    which name is the unique stash tab's layout, joining ``Words.Text`` — the display name the
    client prints, and therefore the one the clipboard repeats — to ``ItemVisualIdentity``.

    The file is a ``.dds`` in the game bundle and a ``.png`` on the CDN at the same path, which
    is what is emitted: the path is published to be fetched, not to describe the bundle.

    **Alternate-art rows are skipped.** They are the same unique with a different picture (the
    foil and race-reward variants), and one of those in place of the ordinary art would show
    the player something that does not look like the item in their stash. Ordinary rows come
    first for the same reason: whichever the layout lists first wins, so a later alternate can
    never displace one.

    Around 110 of trade's uniques have no row here at all — the sanctum relics, the Harbinger
    pieces, a handful renamed out of the client's word list — and they simply get no art. That
    is the whole of what the game says on the subject; guessing a path from the name would be
    a 404 per candidate.
    """
    out: dict[str, str] = {}
    for row in stash_layout:
        if row.get("IsAlternateArt"):
            continue
        wk, vk = row.get("WordsKey"), row.get("ItemVisualIdentityKey")
        if wk is None or vk is None or wk >= len(words) or vk >= len(visuals):
            continue
        name = words[wk].get("Text")
        dds = visuals[vk].get("DDSFile")
        if not name or not dds or not dds.endswith(".dds"):
            continue
        out.setdefault(name, dds[:-len(".dds")] + ".png")
    return out


def build(trade_items: dict, bases: list[dict], classes: list[dict],
          armour: list[dict], tags: list[dict],
          exchange_ids: set[str] | None = None,
          art_by_unique: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    class_name_by_row = {c["_index"]: c.get("Name") or c.get("Id") for c in classes}

    # Game-side base lookup, keyed on display name — the live row wherever several share one.
    game_by_name: dict[str, dict] = {}
    superseded = 0
    for b in bases:
        name = b.get("Name")
        if not name:
            continue
        held = game_by_name.get(name)
        if held is None:
            game_by_name[name] = b
        elif _liveness(b) > _liveness(held):
            game_by_name[name] = b
            superseded += 1

    armour_by_base = {a["BaseItemTypesKey"]: a for a in armour
                      if a.get("BaseItemTypesKey") is not None}

    exchange_ids = exchange_ids or set()
    art_by_unique = art_by_unique or {}
    exchange_matched: set[str] = set()
    records: list[dict] = []
    enriched = 0
    gem_display = 0
    for e in item_entries(trade_items):
        ns = _namespace(e)
        name = e.get("name") or e.get("type")
        if not name:
            continue

        # Gems are the one group whose ``text`` is the name the *game* prints rather than a
        # display composition of the other fields ("Abyssus Ezomyte Burgonet", "Blighted Map
        # (Strand)"). Trade files a transfigured gem under the skill it alters — "Raise Zombie
        # of Falling" is ``Raise Zombie`` with the ``alt_y`` discriminator — so its ``type`` is
        # a name no clipboard ever prints, and keying the record on it left every transfigured
        # gem unfindable from the item text. Key on what the game prints and carry the query
        # term beside it. A Vaal transfigured gem's is the pair, "Vaal Blight (Blight of
        # Atrophy)", which is also exactly what poe.ninja lists it as.
        #
        # This drops ``enriched_from_game_data`` by exactly ``gem_display`` — 3636 to 3373 on
        # the release that introduced it — and that is the fix working rather than a
        # regression. No BaseItemTypes row is named "Raise Zombie of Falling", so those records
        # now match nothing; before, they matched the row for the *base* skill and were handed
        # a metadataId, an item class and a drop level belonging to a different item.
        trade_name = ""
        if ns == "GEM" and e.get("text") and e["text"] != name:
            trade_name, name = name, e["text"]
            gem_display += 1

        rec: dict = {"name": name, "refName": name, "namespace": ns}
        if trade_name:
            rec["tradeName"] = trade_name
        if e.get("disc"):
            rec["tradeDisc"] = e["disc"]

        if ns == "UNIQUE":
            rec["unique"] = {"base": e.get("type", "")}
            # The picture, for a client that has to *show* a unique rather than name it — an
            # unidentified one states only its base, and which of that base's uniques it is
            # can only be answered by looking at it.
            if art := art_by_unique.get(name):
                rec["art"] = art
        else:
            g = game_by_name.get(name)
            if g:
                enriched += 1
                # BaseItemTypes.Id *is* the Metadata/Items/... path, and that path is the only
                # key GGG's public currency-exchange feed states an item by — that feed
                # publishes no names at all, so emitting the id here is the whole of what lets
                # a client join the two.
                if g.get("Id"):
                    rec["metadataId"] = g["Id"]
                    # Whether this item has *ever* traded on the in-game currency exchange —
                    # a fact about the item, unlike the hourly digest the client reads, which
                    # can only say whether one traded in the last hour. Without it the client
                    # cannot tell "not traded on the exchange" from "nobody traded one this
                    # hour", and for a thin item (a Weeping Essence of Greed) the second is
                    # the normal case: poe.ninja has no price for one either, so the check
                    # comes back saying nothing at all. See sources/exchange.py.
                    if g["Id"] in exchange_ids:
                        rec["exchange"] = True
                        exchange_matched.add(g["Id"])
                # The pool namespace this base's modifiers are generated from, and the only
                # thing that says which pool a client should show for it without compiling in a
                # list of names. A base has exactly one — the domains are mutually exclusive.
                #
                # Left off a trade proxy rather than copied from it: trade's one "Map" entry
                # joins to `TradeProxy/MapKey`, and saying 43 there would tell a client that
                # every map in the game rolls from the stackable-currency pool. A record with no
                # domain is answered by its item class, which is exact for that case — see
                # `build_classes`.
                if g.get("ModDomain") is not None and not g["Id"].startswith(_TRADE_PROXY):
                    rec["domain"] = g["ModDomain"]
                cat = class_name_by_row.get(g.get("ItemClassesKey"))
                if cat:
                    rec["craftable"] = {"category": cat}
                if g.get("Width"):
                    rec["w"] = g["Width"]
                if g.get("Height"):
                    rec["h"] = g["Height"]
                if g.get("DropLevel"):
                    rec["dropLevel"] = g["DropLevel"]
                if g.get("IsCorrupted"):
                    rec.setdefault("craftable", {})["corrupted"] = True
                a = armour_by_base.get(g["_index"])
                if a:
                    # Ranges, as [min, max] — these are what distinguish same-named bases
                    # that differ only by which defences they roll (the Two-Toned Boots
                    # family), so keep them even when one end is zero.
                    ar: dict = {}
                    for lo, hi, dst in (("ArmourMin", "ArmourMax", "ar"),
                                        ("EvasionMin", "EvasionMax", "ev"),
                                        ("EnergyShieldMin", "EnergyShieldMax", "es"),
                                        ("WardMin", "WardMax", "ward")):
                        if a.get(lo) or a.get(hi):
                            ar[dst] = [a.get(lo, 0), a.get(hi, 0)]
                    if ar:
                        rec["armour"] = ar
        records.append(rec)

    # Deduplicate on (namespace, name, tradeDisc, unique base): trade lists the same base under
    # several groups when it is queryable more than one way.
    #
    # **A unique is its name *and* its base.** Thirteen names drop on more than one base under
    # one discriminator — Stormblood on both the Sapphire and the Topaz Flask, Precursor's
    # Emblem on five rings, Grand Spectrum and Combat Focus on three jewels each — and keying
    # on the name alone threw 20 of the 1,546 unique entries away. What that costs is not the
    # record: it is `en-items-base.index.bin`, the base -> uniques index an **unidentified**
    # unique is read through. A base whose second unique was dropped answers with one
    # candidate, and one candidate is not a question the client asks — it takes the name. So an
    # unidentified Topaz Flask was confidently read as a Vessel of Vinktar and priced as one.
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in records:
        k = (r["namespace"], r["name"], r.get("tradeDisc"), r.get("unique", {}).get("base"))
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    counts: dict[str, int] = {}
    for r in deduped:
        counts[r["namespace"]] = counts.get(r["namespace"], 0) + 1

    # Counted after the dedup, so it says how many *records* carry the flag rather than how
    # many times it was set: trade lists the same base under several groups.
    flagged = sum(1 for r in deduped if r.get("exchange"))
    with_art = sum(1 for r in deduped if r.get("art"))

    return deduped, {"records": len(deduped), "enriched_from_game_data": enriched,
                     "superseded_rows_passed_over": superseded,
                     "gems_keyed_on_display_name": gem_display,
                     # Both halves, because the gap is the number worth watching: the art join
                     # is on a display name, and a rename upstream would show up here as
                     # uniques quietly losing their picture.
                     "uniques_with_art": with_art,
                     "uniques_without_art": counts.get("UNIQUE", 0) - with_art,
                     "traded_on_currency_exchange": flagged,
                     # Ids the feed named that no base carries. Expected to be small and
                     # non-zero: the feed covers leagues and items the trade API does not
                     # list, and a base retired since it last traded keeps its id in the set.
                     # A number that jumps is the signal that the id join has drifted.
                     "_exchange_ids_unmatched": sorted(exchange_ids - exchange_matched),
                     "by_namespace": counts}


def build_classes(classes: list[dict], category_options: dict[str, str],
                  bases: list[dict] | None = None) -> list[dict]:
    """item-classes.ndjson — the clipboard's "Item Class: X" line to a trade category.

    ``ItemClasses.Name`` is already the plural form the clipboard prints ("Rings",
    "Two Hand Axes"), so it is the join key directly.

    A class also carries the **mod domain** its bases generate from, but only where every one
    of them agrees — 75 of the 86 classes, and none of the 11 that span two, because a class
    holding genuinely different things (Jewels covers ``BASE_JEWEL`` and ``AFFLICTION_JEWEL``)
    can only answer for a base, never for the class. It is a fallback for exactly one shape:
    a record whose game row is a trade proxy and therefore carries no domain of its own. Maps
    are that shape and are the reason it exists — all 511 rows of class ``Maps`` are domain 5,
    while the "Map" trade lists them under is a proxy in 43.
    """
    domains: dict[int, set[int]] = {}
    for b in bases or []:
        if b.get("Id", "").startswith(_TRADE_PROXY) or b.get("ModDomain") is None:
            continue
        key = b.get("ItemClassesKey")
        if key is not None:
            domains.setdefault(key, set()).add(b["ModDomain"])

    out = []
    for c in classes:
        name = c.get("Name")
        if not name:
            continue
        rec = {
            "itemClass": name,
            "id": c.get("Id", ""),
            "tradeCategory": category_options.get(c.get("Id", ""), ""),
        }
        if len(found := domains.get(c["_index"], set())) == 1:
            rec["domain"] = next(iter(found))
        out.append(rec)
    return out
