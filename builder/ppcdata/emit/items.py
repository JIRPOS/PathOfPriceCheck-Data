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


def build(trade_items: dict, bases: list[dict], classes: list[dict],
          armour: list[dict], tags: list[dict]) -> tuple[list[dict], dict]:
    class_name_by_row = {c["_index"]: c.get("Name") or c.get("Id") for c in classes}

    # Game-side base lookup, keyed on display name.
    game_by_name: dict[str, dict] = {}
    for b in bases:
        name = b.get("Name")
        if name:
            game_by_name.setdefault(name, b)

    armour_by_base = {a["BaseItemTypesKey"]: a for a in armour
                      if a.get("BaseItemTypesKey") is not None}

    records: list[dict] = []
    enriched = 0
    for e in item_entries(trade_items):
        ns = _namespace(e)
        name = e.get("name") or e.get("type")
        if not name:
            continue

        rec: dict = {"name": name, "refName": name, "namespace": ns}
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
                     "by_namespace": counts}


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
