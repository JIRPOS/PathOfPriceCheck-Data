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


def _liveness(row: dict) -> tuple[bool, bool]:
    """How likely a BaseItemTypes row is the base that actually drops today, highest first.

    GGG keeps the superseded row when a base is replaced, so several rows share one display
    name: Sacrifice at Dawn is both ``VaalFragment1_2`` and, since fragments became stackable,
    ``CurrencyVaalFragment1_2``. Only the live row's id is ever named by the currency-exchange
    feed, so taking whichever came first emitted an id nothing trades under and left every
    fragment, breachstone and resonator with no exchange price at all.

    Two signals, because neither covers everything: the mod domain (the legacy fragment rows
    are in 14, not 43) and the ``Currency``/``Stackable`` marker GGG names the replacement
    with — which is all that separates the resonators and the Atlas echoes, whose rows are
    both in the stackable domain. Rows that tie keep the table's own order.
    """
    last = row.get("Id", "").rsplit("/", 1)[-1]
    return (row.get("ModDomain") == _STACKABLE_DOMAIN,
            last.startswith("Currency") or "Stackable" in last)


def build(trade_items: dict, bases: list[dict], classes: list[dict],
          armour: list[dict], tags: list[dict]) -> tuple[list[dict], dict]:
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

    # Deduplicate on (namespace, name, tradeDisc): trade lists the same base under several
    # groups when it is queryable more than one way.
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in records:
        k = (r["namespace"], r["name"], r.get("tradeDisc"))
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    counts: dict[str, int] = {}
    for r in deduped:
        counts[r["namespace"]] = counts.get(r["namespace"], 0) + 1

    return deduped, {"records": len(deduped), "enriched_from_game_data": enriched,
                     "superseded_rows_passed_over": superseded,
                     "gems_keyed_on_display_name": gem_display, "by_namespace": counts}


def build_classes(classes: list[dict], category_options: dict[str, str]) -> list[dict]:
    """item-classes.ndjson — the clipboard's "Item Class: X" line to a trade category.

    ``ItemClasses.Name`` is already the plural form the clipboard prints ("Rings",
    "Two Hand Axes"), so it is the join key directly.
    """
    out = []
    for c in classes:
        name = c.get("Name")
        if not name:
            continue
        out.append({
            "itemClass": name,
            "id": c.get("Id", ""),
            "tradeCategory": category_options.get(c.get("Id", ""), ""),
        })
    return out
