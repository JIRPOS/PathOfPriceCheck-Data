"""client mod id -> the wordings and trade ids that mod would be searched by.

Shared by the two emitters that start from a ``Mods.dat`` row rather than from a trade entry:
the per-unique dataset, which starts from the mod ids poewiki says a unique can roll, and the
mod pools, which start from a whole mod domain. Both need the same walk — a mod's stats, the
``stat_descriptions`` block that words them, the stat record carrying the trade id — and both
need their ranges in **displayed units**, because ``Mods.dat`` stores hundredths and
milliseconds raw and leaving that to the client is a silent factor of 100.
"""

from __future__ import annotations

import re

from ..statdesc import Description, primary_variant
from .stats import join_key

# A description block can cover several stats at once ("Adds # to # Fire Damage" is two), and
# a mod's stat list has to be walked longest-run-first to find them. No block covers more.
MAX_SPAN = 4

#: GGG's marker for a wording that is developer content and reaches no player. Left in place by
#: `render` on purpose: it is a marker rather than a label, and it is the only signal an
#: emitter has that the modifier behind it is not one anybody can be holding.
DNT = "[DNT]"

# `[id|Label]` is a term the client links or styles, and `[Label]` where the two are the same.
# The client prints the label alone.
_MARKUP = re.compile(r"\[(?!DNT\])(?:[^\]|]*\|)?([^\]|]*)\]")


def render(text: str) -> str:
    """A description's wording as the client actually prints it.

    Not cosmetic: the trade site indexes the printed form, so the markup is also what stands
    between such a wording and its stat record. "Rare Monsters have [PhysicalThorns|Physical
    Thorns] reflecting # Physical Damage" reaches a real trade id only once it is rendered.
    """
    return _MARKUP.sub(r"\1", text)


def scaled(value: int, dp: int) -> float | int:
    if not dp:
        return value
    s = round(value / (10 ** dp), dp)
    return int(s) if s == int(s) else s


class ModResolver:
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

        self.counts: dict = {"stats_without_description": 0, "wordings_without_stat_record": 0,
                             "wordings_without_trade_id": 0, "ambiguous_wordings": 0,
                             "mods_not_in_client": []}

    def mod_stats(self, mod: dict) -> list[tuple[str, int, int]]:
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
        key = join_key(render(primary_variant(d).text))
        found = self.records.get(key)
        if found:
            return found
        for v in d.variants:
            found = self.records.get(join_key(render(v.text)))
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

    def resolve(self, d: Description, implicit: bool,
                text: str | None = None) -> tuple[str, str, int]:
        """``(wording, trade id, dp)`` for a description. The id can be empty.

        ``text`` pins the lookup to one wording the description can render, which is how a
        modifier rolling a name reaches the id trade files that name under: trade indexes one
        entry per option, so the join is by the wording as always — never by assuming trade
        numbers its options the way the client numbers its rows.

        An empty id means the mod is real and displayable but not searchable, and the caller
        still emits it: a pool list shorter than the pool it describes would contradict itself.

        Trade lists the same wording more than once — 71 of them — usually as one entry
        covering several namespaces and a second covering only ``explicit``. Those duplicates
        agree on the id that matters and are not ambiguity. Two *different* ids behind one
        wording are, and guessing there would produce a confident filter on the wrong stat.
        """
        if text is not None:
            text = render(text)
        found = self.records.get(join_key(text)) if text is not None else self._records_for(d)
        if not found:
            # Trade indexes nothing under this wording. The client's own is the best text there
            # is, which is what the app needs to render the mod.
            self.counts["wordings_without_stat_record"] += 1
            return (text if text is not None else render(primary_variant(d).text)), "", 0
        rec = found[0]
        candidates = {i for r in found for i in self._ids_for(r, implicit)}
        if len(candidates) > 1:
            self.counts["ambiguous_wordings"] += 1
            return rec["ref"], "", rec.get("dp", 0)
        if not candidates:
            self.counts["wordings_without_trade_id"] += 1
            return rec["ref"], "", rec.get("dp", 0)
        return rec["ref"], candidates.pop(), rec.get("dp", 0)

    def spans(self, stats: list[tuple[str, int, int]], count: bool = True):
        """Walk a mod's stats, yielding ``(description, stats it covers)``, longest run first.

        ``count`` is off for a second walk over the same mod: a stat with no wording is one
        fact about the data, not two.
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
