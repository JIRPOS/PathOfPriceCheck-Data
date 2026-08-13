"""stats.ndjson — the clipboard-wording to trade-stat-hash table.

Two sources meet here:

* GGG's ``/api/trade/data/stats`` gives the hashes and, in ``entries[].text``, the wording
  already in '#'-placeholder form.
* The game's ``stat_descriptions.txt`` gives what trade does not: the "reduced" phrasing of
  a stat trade indexes as "increased", fixed-value wordings like "No Physical Damage", and
  decimal placement.

They join on the normalized wording. The wrinkle is the sign in front of a placeholder: trade
writes ``+# to maximum Life`` while the game's ``{0:+d}`` swallows it into ``# to maximum
Life``, so the trade side is folded before matching — and the game's own side is folded before
being emitted, because GGG also writes the sign as literal text (``+{0}% Monster Chaos
Resistance``) where the format spec would have hidden it. See ``_LITERAL_SIGN``.
"""

from __future__ import annotations

import re
from collections.abc import Container

from ..normalize import placeholder_form
from ..statdesc import Description, primary_variant

# Trade renders an explicit sign in front of the placeholder; the game folds it into the
# number. Normalize trade's form so the two sides meet.
_SIGNED_PLACEHOLDER = re.compile(r"(?<![\w#])\+#")

# The same sign, on the side we *emit* — and here it can be either one.
#
# GGG spells a rendered number's sign two ways. `{0:+d} to maximum Life` puts it inside the
# format spec, where it vanishes with the placeholder; `+{0}% Monster Chaos Resistance` writes
# it as literal text, where it survives into the wording. The client cannot tell those apart:
# its normalizer takes a sign as part of the number token every time (NORMALIZATION.md, step
# 2), so `+25% Monster Chaos Resistance` off the clipboard always becomes
# `#% Monster Chaos Resistance`. A wording emitted as `+#%` is therefore indexed under a key
# no item text can ever produce, and the stat is unreachable — not mispriced, simply never
# found.
#
# 47 matcher strings across 34 records shipped that way, among them every `+#% Monster …
# Resistance` and `+#% Monster Physical Damage Reduction`, which is the whole resistance family
# a map rolls and the one map check most wants a verdict on.
_LITERAL_SIGN = re.compile(r"(?<![\w#])[+-]#")

# Modifiers on a stat-description variant that shift the decimal point.
_DP_MODIFIERS = {
    "divide_by_one_hundred": 2,
    "divide_by_one_hundred_2dp": 2,
    "divide_by_one_hundred_2dp_if_required": 2,
    "divide_by_one_hundred_and_negate": 2,
    "milliseconds_to_seconds": 3,
    "milliseconds_to_seconds_1dp": 1,
    "milliseconds_to_seconds_2dp": 2,
    "divide_by_ten_0dp": 0,
    "divide_by_twenty_then_double_0dp": 0,
    "divide_by_one_thousand": 3,
}


def join_key(text: str) -> str:
    """The form both sides agree on."""
    return _SIGNED_PLACEHOLDER.sub("#", placeholder_form(text)).strip()


def rendered_form(text: str) -> str:
    """A description's wording as the client will look it up: sign folded into the number.

    Applied to what is emitted rather than only to what is joined on, which is the difference
    that made `+#% Monster Chaos Resistance` unfindable. See `_LITERAL_SIGN`.
    """
    return _LITERAL_SIGN.sub("#", text)


def _dp_for(d: Description) -> int:
    dp = 0
    for v in d.variants:
        for m in v.modifiers:
            if m in _DP_MODIFIERS:
                dp = max(dp, _DP_MODIFIERS[m])
    return dp


def _widen(d: Description, siblings: list[Description],
           by_text: dict[str, Description]) -> Description:
    """`d` plus the wordings only a sibling file states for the same stat id(s).

    A stat can be worded differently depending on where it rolled: the main file's phrasing is
    also trade's own canonical text, but `heist_equipment_stat_descriptions.txt`,
    `map_stat_descriptions.txt` and the rest override it for their own item class.
    `statdesc.parse` runs once per file, so two blocks that share a stat id still come back as
    two separate `Description` objects, and without this, `by_text` below keeps only the one
    whose wording trade matched — every other file's phrasing for that same stat joins nothing.
    A rare Heist Gear suffix prints "reduced Hiring Fee"; the record trade builds only ever
    carried "reduced Hiring Fee of Rogues", the main file's wording, so the item's own line came
    back unrecognised.

    **Not every same-numbered id is the same stat, though.** GGG reuses a raw stat id across
    genuinely unrelated wordings often enough that `critical_strike_chance_+%` is both "Global
    Critical Strike Chance" in the main file and, in the heist file, a bare "Critical Strike
    Chance" that happens to collide letter-for-letter with a *different* id's
    (`local_critical_strike_chance_+%`) own wording. Folding both blindly by id would have
    handed one wording to two records — exactly what the client cannot resolve. A sibling's
    variant is only safe to add when nothing else already claims its text: either no
    `Description` does, or the claimant is the sibling itself.
    """
    extra = [v for s in siblings if s is not d for v in s.variants
             if by_text.get(join_key(v.text)) in (None, s)]
    return Description(stat_ids=d.stat_ids, variants=d.variants + extra) if extra else d


def _keep(m: dict, prev: dict) -> bool:
    """Whether `m` should displace `prev` as the entry for a wording they now share.

    **Never a negate wording over a plain one.** Folding the sign in collapses `+# to Evasion
    Rating while in Sand Stance` onto the `-#` form GGG lists beside it as that stat's negate
    variant — and once the sign is gone the two say the same thing, because the sign the client
    reads is the number's own. Keeping the negate one would flip a printed `-40` back to `+40`,
    turning an unfindable stat into a wrong one, which is the worse trade.

    Otherwise the most informative wins: a wording repeated with and without an implied value
    keeps the value.
    """
    if m.get("negate", False) != prev.get("negate", False):
        return not m.get("negate", False)
    return len(m) > len(prev)


def _matchers(d: Description) -> list[dict]:
    """One entry per distinct wording the game can render for this stat."""
    seen: dict[str, dict] = {}
    for v in d.variants:
        text = rendered_form(v.text)
        if not text:
            continue
        m: dict = {"string": text}
        if v.negate:
            m["negate"] = True
        if v.fixed_value is not None and "#" not in text:
            m["value"] = v.fixed_value
        prev = seen.get(text)
        if prev is None or _keep(m, prev):
            seen[text] = m
    return list(seen.values())


def _own_matchers(d: Description, key: str, trade_keys: Container[str]) -> list[dict]:
    """The wordings this record — and no sibling record — answers to.

    One description renders several wordings, and trade indexes some of them under a hash of
    their own: "#% chance to gain a Flask Charge when you deal a Critical Strike" and the 100%
    "Gain a Flask Charge when you deal a Critical Strike", "Recover #% of Life on Kill" and
    "Lose #% of Life on Kill", one entry per option of an option stat. Each of those becomes a
    record here, so handing every one of them the description's whole variant list makes
    several records claim the same wording — and the client, which resolves a clipboard line by
    wording, cannot tell them apart. It refuses to guess rather than filter on the wrong stat,
    so the modifier goes unsearched: 16 wordings including every Surgeon's flask. A wording
    trade indexes separately belongs only to the record carrying its id.

    Never empty: ``key`` is the join key of one of ``d``'s own variants, which is how the
    caller reached ``d`` at all, and that variant matches the first arm.
    """
    return [m for m in _matchers(d)
            if join_key(m["string"]) == key or join_key(m["string"]) not in trade_keys]


def _ref_for(d: Description, matchers: list[dict]) -> str:
    """The record's canonical wording — what a roll is stored relative to.

    The description's primary rendering, unless that wording went to a sibling record: a record
    that only answers to "Only affects Passives in Medium Ring" must not call itself the Small
    one. `negate` is relative to this wording, so whichever one becomes it is not the inverse of
    anything — a record keyed by trade's own "Lose #% of Life on Kill" hash stores the roll the
    way that hash indexes it, positive.
    """
    # Folded the same way the matchers were, or the primary wording would never be found among
    # them and every signed stat would fall through to `matchers[0]`.
    primary = rendered_form(primary_variant(d).text)
    ref = primary if any(m["string"] == primary for m in matchers) else matchers[0]["string"]
    for m in matchers:
        if m["string"] == ref:
            m.pop("negate", None)
    return ref


def _ambiguous(records: list[dict]) -> list[str]:
    """Wordings two records both answer to inside one trade namespace.

    That is the shape the client gives up on: it resolves a clipboard line to a wording, and a
    wording reaching two records with a hash each is a filter it would have to guess at.
    """
    owners: dict[tuple[str, str], set[int]] = {}
    for i, r in enumerate(records):
        for m in r["matchers"]:
            for ns, ids in r["trade"]["ids"].items():
                if ids:
                    owners.setdefault((join_key(m["string"]), ns), set()).add(i)
    return sorted({w for (w, _), rs in owners.items() if len(rs) > 1})


def build(trade_stats: dict, descs: list[Description], better_overrides: dict[str, int],
          inverted: set[str]) -> tuple[list[dict], dict]:
    """Return ``(records, stats)`` where records are the ndjson lines to write."""
    from ..sources.trade_api import stat_entries

    by_text: dict[str, Description] = {}
    for d in descs:
        for v in d.variants:
            by_text.setdefault(join_key(v.text), d)

    siblings_by_ids: dict[tuple[str, ...], list[Description]] = {}
    for d in descs:
        siblings_by_ids.setdefault(tuple(d.stat_ids), []).append(d)

    # Group trade entries by their normalized wording: the same stat appears once per
    # namespace (explicit/implicit/fractured/crafted/enchant/...), and those all belong to
    # one record whose trade.ids map is keyed by namespace.
    grouped: dict[str, dict[str, list[str]]] = {}
    order: list[str] = []
    options: dict[str, dict] = {}
    for e in stat_entries(trade_stats):
        text = e.get("text", "")
        if not text:
            continue
        key = join_key(text)
        if key not in grouped:
            grouped[key] = {}
            order.append(key)
        grouped[key].setdefault(e["_group"], []).append(e["id"])
        if "option" in e:
            options[key] = e["option"]

    records: list[dict] = []
    matched = 0
    narrowed = 0
    for key in order:
        ids = grouped[key]
        d = by_text.get(key)
        if d is not None:
            d = _widen(d, siblings_by_ids.get(tuple(d.stat_ids), ()), by_text)
            matched += 1
            matchers = _own_matchers(d, key, grouped.keys())
            ref = _ref_for(d, matchers)
            if len(matchers) < len(_matchers(d)):
                narrowed += 1
            dp = _dp_for(d)
        else:
            # No game description for this wording — trade indexes some stats the client
            # never renders (pseudo groups, crucible mod text). The trade wording is still
            # a perfectly good single matcher.
            ref = key
            matchers = [{"string": key}]
            dp = 0

        rec: dict = {"ref": ref, "matchers": matchers,
                     "better": better_overrides.get(ref, 1)}
        if dp:
            rec["dp"] = dp
        trade: dict = {"ids": ids}
        if ref in inverted:
            trade["inverted"] = True
        if key in options:
            trade["option"] = True
            rec["options"] = options[key].get("options", [])
        rec["trade"] = trade
        records.append(rec)

    # A curated entry that matches no record is dead weight that reads as if it were doing
    # something. Surface it so it gets fixed or dropped rather than quietly rotting.
    all_refs = {r["ref"] for r in records}
    stats = {
        "trade_wordings": len(order),
        "matched_to_game_data": matched,
        "unmatched": len(order) - matched,
        "with_negate_matcher": sum(
            1 for r in records if any(m.get("negate") for m in r["matchers"])),
        "with_value_matcher": sum(
            1 for r in records if any("value" in m for m in r["matchers"])),
        # Records that gave a wording up to the sibling holding trade's own hash for it.
        "narrowed_to_own_wordings": narrowed,
        # Must be 0: two records answering to one wording in one namespace is exactly what the
        # client cannot resolve, and it drops the modifier rather than guess.
        "wordings_ambiguous_in_a_namespace": _ambiguous(records),
        "stale_better_overrides": sorted(set(better_overrides) - all_refs),
        "stale_inverted": sorted(inverted - all_refs),
    }
    return records, stats
