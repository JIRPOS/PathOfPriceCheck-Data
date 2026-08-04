"""unique-mods.ndjson — which modifiers each unique can roll, and which of them vary.

The problem this exists to solve: a unique's modifier can be variable without printing a
range. Ralakesh's Impatience rolls either Power, Frenzy or Endurance charges — three mods,
each 1..1 — and the clipboard prints the one it got exactly like a fixed mod. A Watcher's Eye
picks two or three mods out of 93. Nothing in the item text distinguishes "this unique always
has this" from "this unique happened to roll this out of a pool", and that difference is
routinely the difference between vendor trash and several divines.

Three sources meet here:

* **poewiki's ``item_mods``** (``sources/wiki``) says *which* GGG mod ids a unique can roll and
  which of them are random. Mapping only — no numbers.
* **``Mods.dat``** gives each of those mod ids its stats and its min/max rolls.
* **the stat records** built for ``en-stats.ndjson`` give the trade stat hash, reached the same
  way as everywhere else in this builder: client stat id → its ``stat_descriptions`` block →
  the ``#``-placeholder wording → the trade id.

So a pool mod arrives with the trade filter and the range needed to search it, and the app can
offer a mod the item does not have — which is the whole point of a pool.

Ranges are emitted in **displayed units**, with the record's ``dp`` already applied, because
that is the unit the clipboard prints and the trade filters take. ``Mods.dat`` stores
hundredths and milliseconds raw; leaving that to the client would be a silent factor-of-100.
"""

from __future__ import annotations

import re

from ..statdesc import Description, primary_variant
from .stats import join_key

# A description block can cover several stats at once ("Adds # to # Fire Damage" is two), and
# a mod's stat list has to be walked longest-run-first to find them. No block covers more.
MAX_SPAN = 4

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_NUM = r"(?:\d+|" + "|".join(_NUMBER_WORDS) + r")"
_COUNT_RE = re.compile(
    rf"^(?P<lo>{_NUM})(?:\s+(?:to|or)\s+(?P<hi>{_NUM}))?\b", re.IGNORECASE)

_SEGMENT_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<(?:span|/span|div|/div|b|/b|i|/i|small|/small)\b[^>]*>",
                     re.IGNORECASE)
# "[[List of notable ascendancy passive skills|Ascendancy Notable]]" renders as its label.
_WIKILINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]")


def _to_number(tok: str) -> int:
    return int(tok) if tok.isdigit() else _NUMBER_WORDS[tok.lower()]


def hint_text(raw: str | None) -> str:
    """The wiki's placeholder text as prose.

    The ``text`` column is display HTML: wiki links, ``<span>`` colouring, ``<br>`` between
    several placeholders, and the whole thing wrapped in the angle brackets the wiki uses to
    mark "something variable goes here". None of that belongs in the bundle, but the prose
    does — it is the only statement of how many of a pool actually roll.
    """
    if not raw:
        return ""
    t = _WIKILINK_RE.sub(r"\1", _TAG_RE.sub("", _SEGMENT_RE.sub(" / ", raw)))
    t = re.sub(r"\s+", " ", t.replace("<", " ").replace(">", " ")).strip()
    return t.strip(" /:")


def parse_count(hint: str) -> list[int] | None:
    """``"Two or Three random aura modifiers"`` -> ``[2, 3]``.

    How many of a pool roll is only ever stated in this prose, so it is parsed rather than
    inferred: a Watcher's Eye with 91 pool mods rolls two or three of them, and an app that
    assumed "all of them" would build a search nothing can satisfy.

    A hint that describes several sub-pools at once ("One Endurance Charge mod / One Frenzy
    Charge mod / ...", which is Precursor's Emblem) yields nothing: the leading number counts
    only its own segment, and the wiki gives no way to tell which pool mod belongs to which.
    Better for the app to know the count is unknown than to believe a wrong one.
    """
    if " / " in hint:
        return None
    m = _COUNT_RE.match(hint)
    if not m:
        return None
    lo = _to_number(m.group("lo"))
    hi = _to_number(m.group("hi")) if m.group("hi") else lo
    return [lo, hi] if hi >= lo else [hi, lo]


def _truthy(v) -> bool:
    return str(v) in ("1", "True", "true")


def _scaled(value: int, dp: int) -> float | int:
    if not dp:
        return value
    scaled = round(value / (10 ** dp), dp)
    return int(scaled) if scaled == int(scaled) else scaled


class _Resolver:
    """client mod id -> the trade filters that mod would be searched by."""

    def __init__(self, mods: list[dict], stats: list[dict], descs: list[Description],
                 stat_records: list[dict]):
        self.mod_by_id = {m["Id"]: m for m in mods if m.get("Id")}
        self.stat_id_by_row = {s["_index"]: s["Id"] for s in stats}

        # First writer wins, matching statdesc.by_english_text: the canonical block precedes
        # its skill-specific overrides.
        self.desc_by_stats: dict[tuple[str, ...], Description] = {}
        for d in descs:
            self.desc_by_stats.setdefault(tuple(d.stat_ids), d)

        # Every wording a record answers to, so a description reaches its record through any
        # of its variants and not just the primary one.
        self.records: dict[str, list[dict]] = {}
        for rec in stat_records:
            keys = {join_key(rec["ref"])}
            keys.update(join_key(m["string"]) for m in rec["matchers"])
            for k in keys:
                self.records.setdefault(k, []).append(rec)

        self.counts = {"stats_without_description": 0, "wordings_without_stat_record": 0,
                       "wordings_without_trade_id": 0, "ambiguous_wordings": 0,
                       "mods_with_no_searchable_stat": 0, "mods_not_in_client": []}

    def _mod_stats(self, mod: dict) -> list[tuple[str, int, int]]:
        """``[(client stat id, min, max)]`` in the order the mod lists them.

        Stops at the first slot it cannot read rather than closing the hole. The slots are
        packed — no mod of the 40,348 has a gap — but if one ever did, skipping would make two
        non-adjacent stats adjacent and they could then match a two-stat wording that describes
        neither. Losing a trailing filter is recoverable; a filter on the wrong stat is not.
        """
        out = []
        for i in range(1, 9):
            row = mod.get(f"StatsKey{i}")
            if row is None:
                break
            sid = self.stat_id_by_row.get(row)
            if sid is None:
                break
            out.append((sid, mod.get(f"Stat{i}Min", 0) or 0, mod.get(f"Stat{i}Max", 0) or 0))
        return out

    def _records_for(self, d: Description) -> list[dict]:
        key = join_key(primary_variant(d).text)
        found = self.records.get(key)
        if found:
            return found
        for v in d.variants:
            found = self.records.get(join_key(v.text))
            if found:
                return found
        return []

    def _ids_for(self, rec: dict, implicit: bool) -> list[str]:
        ids = rec.get("trade", {}).get("ids", {})
        want = "implicit" if implicit else "explicit"
        group = ids.get(want)
        if not group:
            # A wording trade indexes in exactly one namespace resolves to it whatever we
            # expected; more than one candidate does not, because picking would be a guess.
            # This is not a stretch: all 42 filters it produces are Sanctum relic mods
            # (`sanctum.*`) and one talisman enchantment (`enchant.*`) — items trade genuinely
            # indexes outside `explicit`, which the wiki's is_implicit flag cannot express.
            usable = [v for g, v in ids.items() if v and g != "pseudo"]
            if len(usable) != 1:
                return []
            group = usable[0]
        return list(group)

    def _resolve(self, d: Description, implicit: bool) -> tuple[str, str, int]:
        """``(wording, trade id, dp)`` for a description. The id can be empty.

        An empty id means the mod is real and displayable but not searchable, and the filter is
        still emitted: a pool list shorter than the pool it describes would contradict its own
        count hint, and "two or three of these 91" is only true if all 91 are listed.

        Trade lists the same wording more than once — 71 of them — usually as one entry
        covering several namespaces and a second covering only ``explicit``. Those duplicates
        agree on the id that matters and are not ambiguity. Two *different* ids behind one
        wording are, and guessing there would produce a confident filter on the wrong stat.
        """
        found = self._records_for(d)
        if not found:
            # Trade indexes nothing under this wording. The client's own is the best text there
            # is, which is what the app needs to render the mod.
            self.counts["wordings_without_stat_record"] += 1
            return primary_variant(d).text, "", 0
        rec = found[0]
        candidates = {i for r in found for i in self._ids_for(r, implicit)}
        if len(candidates) > 1:
            self.counts["ambiguous_wordings"] += 1
            return rec["ref"], "", rec.get("dp", 0)
        if not candidates:
            self.counts["wordings_without_trade_id"] += 1
            return rec["ref"], "", rec.get("dp", 0)
        return rec["ref"], candidates.pop(), rec.get("dp", 0)

    def filters(self, mod_id: str, implicit: bool) -> list[dict] | None:
        """The trade filters for one mod id, or None when the client has no such mod."""
        mod = self.mod_by_id.get(mod_id)
        if mod is None:
            self.counts["mods_not_in_client"].append(mod_id)
            return None

        stats = self._mod_stats(mod)
        out: list[dict] = []
        i = 0
        while i < len(stats):
            d = None
            span = 0
            for n in range(min(MAX_SPAN, len(stats) - i), 0, -1):
                d = self.desc_by_stats.get(tuple(s[0] for s in stats[i:i + n]))
                if d is not None:
                    span = n
                    break
            if d is None:
                # Hidden stats have no wording at all — cosmetic footprints, monster-only
                # behaviour. Nothing to search, so they are simply not filters.
                self.counts["stats_without_description"] += 1
                i += 1
                continue

            ref, trade_id, dp = self._resolve(d, implicit)
            f: dict = {"ref": ref,
                       "range": [[_scaled(lo, dp), _scaled(hi, dp)] for _, lo, hi in
                                 stats[i:i + span]]}
            if trade_id:
                f["tradeId"] = trade_id
            out.append(f)
            i += span
        return out


def build(wiki_rows: list[dict], mods: list[dict], stats: list[dict],
          descs: list[Description], stat_records: list[dict],
          known_uniques: set[str] | None = None) -> tuple[list[dict], dict]:
    """Return ``(records, stats)``; records are the ndjson lines, keyed ``UNIQUE::<name>``.

    ``known_uniques`` is the set of unique names the trade API knows. A wiki page outside it
    is dropped: legacy and removed uniques are not searchable, and a name that should be there
    but is not is a join bug worth seeing in the counts.
    """
    resolver = _Resolver(mods, stats, descs, stat_records)

    # name -> {base, rows}
    by_name: dict[str, dict] = {}
    for r in wiki_rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        item = by_name.setdefault(name, {"base": (r.get("base") or "").strip(), "rows": []})
        item["rows"].append(r)

    records: list[dict] = []
    skipped_unknown: list[str] = []
    pool_items = 0
    pool_mods = 0
    fixed_mods = 0
    for name in sorted(by_name):
        if known_uniques is not None and name not in known_uniques:
            skipped_unknown.append(name)
            continue
        item = by_name[name]

        fixed: list[dict] = []
        pools: dict[tuple[bool, str], dict] = {}
        unlisted: list[str] = []

        for r in item["rows"]:
            hint = hint_text(r.get("hint"))
            mod_id = (r.get("mod") or "").strip()
            if not mod_id:
                # A row with prose and no id is a pool the wiki does not enumerate — the
                # general Synthesis implicit pool, "one random Delve modifier". Carried
                # verbatim so the app can say what it cannot search instead of implying the
                # item has nothing more.
                if hint and hint not in unlisted:
                    unlisted.append(hint)
                continue

            implicit = _truthy(r.get("impl"))
            filters = resolver.filters(mod_id, implicit)
            if filters is None:
                continue  # a stale wiki id; the client has no such mod
            if not filters:
                # Every stat this mod grants is unsearchable — cosmetic footprints, hidden
                # behaviour. Counted, because it makes a pool list shorter than the pool.
                resolver.counts["mods_with_no_searchable_stat"] += 1
                continue

            entry: dict = {"mod": mod_id, "filters": filters}
            if implicit:
                entry["implicit"] = True

            if _truthy(r.get("rnd")):
                key = (implicit, hint)
                pool = pools.setdefault(key, {"mods": [], "hint": hint, "implicit": implicit})
                pool["mods"].append(entry)
            else:
                fixed.append(entry)

        if not fixed and not pools and not unlisted:
            continue

        rec: dict = {"name": name}
        if item["base"]:
            rec["base"] = item["base"]
        if fixed:
            rec["fixed"] = sorted(fixed, key=lambda e: e["mod"])
            fixed_mods += len(fixed)
        if pools:
            out_pools = []
            for (implicit, hint), pool in sorted(pools.items()):
                p: dict = {"mods": sorted(pool["mods"], key=lambda e: e["mod"])}
                count = parse_count(hint)
                if count:
                    p["count"] = count
                if hint:
                    p["hint"] = hint
                if implicit:
                    p["implicit"] = True
                out_pools.append(p)
                pool_mods += len(p["mods"])
            rec["pools"] = out_pools
            pool_items += 1
        if unlisted:
            rec["unlisted"] = sorted(unlisted)
        records.append(rec)

    counts = resolver.counts
    missing = counts.pop("mods_not_in_client")
    return records, {
        "uniques": len(records),
        "with_a_random_pool": pool_items,
        "fixed_mods": fixed_mods,
        "pool_mods": pool_mods,
        "wiki_rows": len(wiki_rows),
        "wiki_mod_ids_not_in_client": len(set(missing)),
        "not_in_trade_data": len(skipped_unknown),
        **counts,
        "_missing_examples": sorted(set(missing))[:10],
        "_not_in_trade_examples": skipped_unknown[:10],
    }
