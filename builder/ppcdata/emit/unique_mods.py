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

from ..statdesc import Description, Variant, pinned_value, primary_variant, spec_accepts
from .stats import join_key

# A description block can cover several stats at once ("Adds # to # Fire Damage" is two), and
# a mod's stat list has to be walked longest-run-first to find them. No block covers more.
MAX_SPAN = 4

# How many wordings one modifier may expand into. Forbidden Shako's is the widest that exists
# — four equipment slots times 164 support gems — and the cap is here so that a table growing
# a digit becomes a visible count rather than a bundle nobody notices doubling.
MAX_OPTIONS = 1024

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


def _substitute(text: str, placeholders: list[int], stat_index: int, name: str) -> str | None:
    """Replace the '#' that stands for `stat_index` with `name`.

    Which '#' that is comes from the description's own ``{N}`` numbering, not from counting:
    "Skills Socketed in your Helmet are Supported by level {2} {1}" prints its two stats in
    the opposite order to the order it lists them.
    """
    if stat_index not in placeholders:
        return None
    nth = placeholders.index(stat_index)
    parts = text.split("#")
    if nth >= len(parts) - 1:
        return None
    return "#".join(parts[:nth + 1]) + name + "#".join(parts[nth + 1:])


class _Resolver:
    """client mod id -> the trade filters that mod would be searched by."""

    def __init__(self, mods: list[dict], stats: list[dict], descs: list[Description],
                 stat_records: list[dict], indexables: dict[str, list[str]] | None = None):
        self.indexables = indexables or {}
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
                       "mods_with_no_searchable_stat": 0,
                       "mods_rolling_a_named_option": 0, "named_options": 0,
                       "named_options_without_trade_id": 0,
                       "mods_over_the_option_cap": [], "mods_not_in_client": []}

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

    def _resolve(self, d: Description, implicit: bool,
                 text: str | None = None) -> tuple[str, str, int]:
        """``(wording, trade id, dp)`` for a description. The id can be empty.

        ``text`` pins the lookup to one wording the description can render, which is how a
        modifier rolling a name reaches the id trade files that name under: trade indexes one
        entry per option, so the join is by the wording as always — never by assuming trade
        numbers its options the way the client numbers its rows.

        An empty id means the mod is real and displayable but not searchable, and the filter is
        still emitted: a pool list shorter than the pool it describes would contradict its own
        count hint, and "two or three of these 91" is only true if all 91 are listed.

        Trade lists the same wording more than once — 71 of them — usually as one entry
        covering several namespaces and a second covering only ``explicit``. Those duplicates
        agree on the id that matters and are not ambiguity. Two *different* ids behind one
        wording are, and guessing there would produce a confident filter on the wrong stat.
        """
        found = self.records.get(join_key(text)) if text is not None else self._records_for(d)
        if not found:
            # Trade indexes nothing under this wording. The client's own is the best text there
            # is, which is what the app needs to render the mod.
            self.counts["wordings_without_stat_record"] += 1
            return (text if text is not None else primary_variant(d).text), "", 0
        rec = found[0]
        candidates = {i for r in found for i in self._ids_for(r, implicit)}
        if len(candidates) > 1:
            self.counts["ambiguous_wordings"] += 1
            return rec["ref"], "", rec.get("dp", 0)
        if not candidates:
            self.counts["wordings_without_trade_id"] += 1
            return rec["ref"], "", rec.get("dp", 0)
        return rec["ref"], candidates.pop(), rec.get("dp", 0)

    def _spans(self, stats: list[tuple[str, int, int]], count: bool = True):
        """Walk a mod's stats, yielding ``(description, stats it covers)``, longest run first.

        ``count`` is off for the option pass, which walks the same mod a second time: a stat
        with no wording is one fact about the data, not two.
        """
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
                if count:
                    self.counts["stats_without_description"] += 1
                i += 1
                continue
            yield d, stats[i:i + span]
            i += span

    def _named_options(self, d: Description,
                       span: list[tuple[str, int, int]]) -> list[tuple[str, list[int]]] | None:
        """``[(wording, stat indices still placeheld)]`` when this span's roll is a name.

        Two shapes, and a modifier can be both at once. A description may render **one
        variant per value** — sixteen wordings, one per minion type, each pinned by its own
        range spec — and it may declare an **indexable** stat, whose value is a row in a
        client table of names. Forbidden Shako is both: four equipment slots as variants,
        times 164 support gems as an index.

        None when neither applies, which is every ordinary modifier.
        """
        pins = [pinned_value(v.ranges[0]) if v.ranges else None for v in d.variants]
        lo0, hi0 = span[0][1], span[0][2]
        if len(d.variants) > 1 and all(p is not None for p in pins) and hi0 > lo0:
            chosen: list[Variant] = [v for v, p in zip(d.variants, pins) if lo0 <= p <= hi0]
            consumed = {0}  # the wording states which value it is, so it is not a range
        else:
            # One wording, picked the way the "+" and "-" halves of a description are told
            # apart: by which range spec covers the rolls this mod actually has.
            match = next((v for v in d.variants
                          if all(spec_accepts(s, st[1], st[2])
                                 for s, st in zip(v.ranges, span))), None)
            chosen = [match or primary_variant(d)]
            consumed = set()

        idx = next((v.indexable for v in chosen if v.indexable), None)
        out: list[tuple[str, list[int]]] = []
        for v in chosen:
            if idx is None:
                out.append((v.text, [p for p in v.placeholders if p not in consumed]))
                continue
            kind, stat_index = idx
            names = self.indexables.get(kind) or []
            if stat_index >= len(span):
                return None
            lo, hi = span[stat_index][1], span[stat_index][2]
            rest = [p for p in v.placeholders if p not in consumed and p != stat_index]
            for value in range(lo, hi + 1):
                if not 1 <= value <= len(names):
                    return None  # the table cannot answer the whole roll; do not guess half
                text = _substitute(v.text, v.placeholders, stat_index, names[value - 1])
                if text is None:
                    return None
                out.append((text, rest))

        if len(out) < 2:
            return None
        return out

    def _filter_for(self, d: Description, implicit: bool, text: str,
                    placeheld: list[int], span: list[tuple[str, int, int]]) -> dict:
        """One filter dict, its range covering the stats the wording still leaves placeheld."""
        ref, trade_id, dp = self._resolve(d, implicit, text)
        f: dict = {"ref": ref,
                   "range": [[_scaled(span[p][1], dp), _scaled(span[p][2], dp)]
                             for p in placeheld if p < len(span)]}
        if trade_id:
            f["tradeId"] = trade_id
        return f

    def filters(self, mod_id: str, implicit: bool) -> list[dict] | None:
        """The trade filters for one mod id, or None when the client has no such mod."""
        mod = self.mod_by_id.get(mod_id)
        if mod is None:
            self.counts["mods_not_in_client"].append(mod_id)
            return None

        out: list[dict] = []
        for d, span in self._spans(self._mod_stats(mod)):
            ref, trade_id, dp = self._resolve(d, implicit)
            f: dict = {"ref": ref,
                       "range": [[_scaled(lo, dp), _scaled(hi, dp)] for _, lo, hi in span]}
            if trade_id:
                f["tradeId"] = trade_id
            out.append(f)
        return out

    def option_filters(self, mod_id: str, implicit: bool) -> list[list[dict]] | None:
        """One filter list per wording this modifier can roll, or None when it rolls one.

        A modifier whose value is a name is a pool of exactly one member, and nothing outside
        the client's own data says so: the wiki records it as a modifier the unique always
        has, which it is — what varies is *which* of them, and that is the whole of what the
        copy in hand is worth searching for.
        """
        mod = self.mod_by_id.get(mod_id)
        if mod is None:
            return None

        spans = list(self._spans(self._mod_stats(mod), count=False))
        opts = [(d, span, self._named_options(d, span)) for d, span in spans]
        expanding = [o for o in opts if o[2]]
        if len(expanding) != 1:
            # None is the ordinary case. More than one would be a product of products, which
            # no modifier in the data is, and multiplying them out on a guess is worse than
            # leaving the modifier as the single filter it already was.
            return None
        if len(expanding[0][2]) > MAX_OPTIONS:
            self.counts["mods_over_the_option_cap"].append(mod_id)
            return None

        self.counts["mods_rolling_a_named_option"] += 1
        out: list[list[dict]] = []
        for text, placeheld in expanding[0][2]:
            fs: list[dict] = []
            for d, span in spans:
                if (d, span) == (expanding[0][0], expanding[0][1]):
                    fs.append(self._filter_for(d, implicit, text, placeheld, span))
                else:
                    ref, trade_id, dp = self._resolve(d, implicit)
                    f: dict = {"ref": ref,
                               "range": [[_scaled(lo, dp), _scaled(hi, dp)] for _, lo, hi in span]}
                    if trade_id:
                        f["tradeId"] = trade_id
                    fs.append(f)
            self.counts["named_options"] += 1
            if not any(f.get("tradeId") for f in fs):
                self.counts["named_options_without_trade_id"] += 1
            out.append(fs)
        return out


def build(wiki_rows: list[dict], mods: list[dict], stats: list[dict],
          descs: list[Description], stat_records: list[dict],
          known_uniques: set[str] | None = None,
          indexables: dict[str, list[str]] | None = None) -> tuple[list[dict], dict]:
    """Return ``(records, stats)``; records are the ndjson lines, keyed ``UNIQUE::<name>``.

    ``known_uniques`` is the set of unique names the trade API knows. A wiki page outside it
    is dropped: legacy and removed uniques are not searchable, and a name that should be there
    but is not is a join bug worth seeing in the counts.
    """
    resolver = _Resolver(mods, stats, descs, stat_records, indexables)

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
        option_pools: list[dict] = []
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

            # A modifier whose value is a name is a pool of one, whatever the wiki calls it:
            # every copy has the modifier and no two copies need have the same wording, so it
            # is the one thing about the item worth searching for. It cannot go through the
            # `fixed`/`rnd` split below, because a single filter would claim this copy rolled
            # whichever option the description happens to render first.
            options = resolver.option_filters(mod_id, implicit)
            if options:
                p: dict = {"mods": [{"mod": mod_id, "filters": fs} for fs in options],
                           "count": [1, 1]}
                if hint:
                    p["hint"] = hint
                if implicit:
                    p["implicit"] = True
                    for e in p["mods"]:
                        e["implicit"] = True
                option_pools.append(p)
                continue

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

        if not fixed and not pools and not option_pools and not unlisted:
            continue

        rec: dict = {"name": name}
        if item["base"]:
            rec["base"] = item["base"]
        if fixed:
            rec["fixed"] = sorted(fixed, key=lambda e: e["mod"])
            fixed_mods += len(fixed)
        if pools or option_pools:
            out_pools = []
            for (implicit, hint), pool in sorted(pools.items()):
                p = {"mods": sorted(pool["mods"], key=lambda e: e["mod"])}
                count = parse_count(hint)
                if count:
                    p["count"] = count
                if hint:
                    p["hint"] = hint
                if implicit:
                    p["implicit"] = True
                out_pools.append(p)
            out_pools.extend(sorted(option_pools, key=lambda p: p["mods"][0]["mod"]))
            pool_mods += sum(len(p["mods"]) for p in out_pools)
            rec["pools"] = out_pools
            pool_items += 1
        if unlisted:
            rec["unlisted"] = sorted(unlisted)
        records.append(rec)

    counts = resolver.counts
    missing = counts.pop("mods_not_in_client")
    over_cap = counts.pop("mods_over_the_option_cap")
    counts["mods_over_the_option_cap"] = sorted(set(over_cap))
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
