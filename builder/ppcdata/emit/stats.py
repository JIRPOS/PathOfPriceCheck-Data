"""stats.ndjson — the clipboard-wording to trade-stat-hash table.

Two sources meet here:

* GGG's ``/api/trade/data/stats`` gives the hashes and, in ``entries[].text``, the wording
  already in '#'-placeholder form.
* The game's ``stat_descriptions.txt`` gives what trade does not: the "reduced" phrasing of
  a stat trade indexes as "increased", fixed-value wordings like "No Physical Damage", and
  decimal placement.

They join on the normalized wording. The one wrinkle is that trade writes ``+# to maximum
Life`` while the game's ``{0:+d}`` placeholder swallows the sign into ``# to maximum Life``,
so the trade side is normalized before matching.
"""

from __future__ import annotations

import re

from ..normalize import placeholder_form
from ..statdesc import Description, primary_variant

# Trade renders an explicit sign in front of the placeholder; the game folds it into the
# number. Normalize trade's form so the two sides meet.
_SIGNED_PLACEHOLDER = re.compile(r"(?<![\w#])\+#")

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


def _dp_for(d: Description) -> int:
    dp = 0
    for v in d.variants:
        for m in v.modifiers:
            if m in _DP_MODIFIERS:
                dp = max(dp, _DP_MODIFIERS[m])
    return dp


def _matchers(d: Description) -> list[dict]:
    """One entry per distinct wording the game can render for this stat."""
    seen: dict[str, dict] = {}
    for v in d.variants:
        text = v.text
        if not text:
            continue
        m: dict = {"string": text}
        if v.negate:
            m["negate"] = True
        if v.fixed_value is not None and "#" not in text:
            m["value"] = v.fixed_value
        prev = seen.get(text)
        # Keep the most informative duplicate: a wording repeated with and without an
        # implied value should keep the value.
        if prev is None or (len(m) > len(prev)):
            seen[text] = m
    return list(seen.values())


def build(trade_stats: dict, descs: list[Description], better_overrides: dict[str, int],
          inverted: set[str]) -> tuple[list[dict], dict]:
    """Return ``(records, stats)`` where records are the ndjson lines to write."""
    from ..sources.trade_api import stat_entries

    by_text: dict[str, Description] = {}
    for d in descs:
        for v in d.variants:
            by_text.setdefault(join_key(v.text), d)

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
    for key in order:
        ids = grouped[key]
        d = by_text.get(key)
        if d is not None:
            matched += 1
            ref = primary_variant(d).text
            matchers = _matchers(d)
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
        "stale_better_overrides": sorted(set(better_overrides) - all_refs),
        "stale_inverted": sorted(inverted - all_refs),
    }
    return records, stats
