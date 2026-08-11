"""mod-pools.ndjson — every modifier a mod domain can spawn, as wordings.

Every other asset here starts from an item in hand: a wording the clipboard printed, a base
the trade site lists. This one starts from a **pool** — the whole set of modifiers a kind of
item can roll, whether or not anyone is holding one. The app's map check needs it for exactly
one thing: letting a player rate a modifier they have not met yet, in Settings, instead of
only rating what a popup has shown them.

**It describes; it never gates.** The pool is what spawns *naturally*, which is strictly less
than what an item can print — an essence, a craft, a veiled mod or Harvest all put modifiers
on an item whose weights would never have produced them. On top of that the list hygiene
below is a naming convention rather than data. So a printed modifier the pool does not contain
is normal, not an error, and nothing may use this asset to reject a line, hide it, or decide
it failed to parse.

One record is one **wording-set**, not one mod row: tier variants of one affix all render the
same wordings and a verdict attaches to a wording, so the 800 domain-5 affix rows collapse to
about 160 entries. ``min``/``max`` span the lowest and highest tier, in displayed units with
``dp`` applied, exactly as ``unique_mods`` emits its ranges — they are what lets a pasted map
regex be tested against a rendered line rather than against a placeholder.
"""

from __future__ import annotations

import collections

from ..statdesc import Description
from .mod_resolver import DNT, ModResolver, scaled

#: Which ``(domain, generation type)`` pairs are emitted, and nothing else until something
#: asks for one. Domain 5 is ``AREA``, the pool every item that opens in the map device rolls
#: from — ordinary, nightmare and Originator maps, unique maps, invitations and expedition
#: logbooks alike. Domain 39 is charts, a domain dat-schema does not name.
#:
#: The generation types are the ones a player *rolls*: prefixes and suffixes, the Vaal
#: corruption implicits, the legacy Tempest/Eclipse set, and the modifiers an expedition
#: logbook, a memory altar and a chart's voyage grant. Generation 3 is the fixed implicit a
#: base simply has, which is why domain 5 leaves it out — 545 wordings nobody rolls and nobody
#: rates would swamp a list meant to be read. Domain 39's one generation-3 row is the
#: exception that proves it: an unsailed chart prints "Voyage Modifier will be revealed once
#: Charted" *instead of* the modifier, so it is the only thing there is to rate.
POOL_GENERATIONS = {
    5: (1, 2, 5, 8, 23, 36),
    39: (1, 2, 3, 37),
}

#: Generation types whose modifiers trade indexes as implicits rather than explicits.
_IMPLICIT_GENERATIONS = (3, 5)

#: Mod-id fragments whose entries are left out. Borrowed from the idea of spawn weights and
#: doing far less: ``CorruptedSideArea`` is a Vaal side area's own modifiers, which never print
#: on anything a player can copy, and ``Map2Tier`` is a legacy map series. Roughly 52 of 208
#: domain-5 affix wording-sets. This is a naming convention rather than data, it is allowed to
#: be imperfect in both directions, and the cost of a mistake either way is one row in a
#: searchable list.
NEVER_PRINTED = ("CorruptedSideArea", "Map2Tier")


def _dropped(mod_ids: list[str], wordings: list[str]) -> bool:
    """True when a wording-set is one no player can be holding.

    Two independent reasons, and both ask about *every* member rather than any: a wording a
    live affix shares with a side-area mod is one the player can be holding, and dropping it
    would take a rateable modifier off the list.

    The second is GGG's own marker. A `[DNT]` wording is developer content the client does not
    show — five entries, among them a Sirus modifier and the expedition chest counters — and it
    is the one case where the data says outright that nothing prints.
    """
    return (all(any(frag in mid for frag in NEVER_PRINTED) for mid in mod_ids)
            or all(w.startswith(DNT) for w in wordings))


def _wordings(resolver: ModResolver, mod: dict,
              implicit: bool) -> list[tuple[str, str, list[tuple[int, int]]]]:
    """``[(wording, trade id, [(min, max)] in displayed units)]`` for one mod row."""
    out = []
    for d, span in resolver.spans(resolver.mod_stats(mod)):
        ref, trade_id, dp = resolver.resolve(d, implicit)
        # One bound per '#' the wording prints, which is what a rendered line needs. A wording
        # that shows no number at all gets none, and its record says so with a null min/max.
        n = min(ref.count("#"), len(span))
        out.append((ref, trade_id, [(scaled(span[i][1], dp), scaled(span[i][2], dp))
                                    for i in range(n)]))
    return out


def _name(rows: list[dict]) -> str:
    """The affix name for a wording-set — ``Mods.Name``, what the client prints with Advanced
    Mod Descriptions on.

    A wording-set's rows can disagree: "Twinned" and "of Twinning" word the same thing as a
    prefix and as a suffix, and the tier ladders of one affix are not always named alike. The
    most common non-empty name wins and the count of sets where they disagreed is reported,
    because the name is decoration here — the verdict attaches to the wording underneath it.
    """
    names = [r.get("Name") or "" for r in rows if r.get("Name")]
    if not names:
        return ""
    return collections.Counter(names).most_common(1)[0][0]


def build(mods: list[dict], stats: list[dict], descs: list[Description],
          stat_records: list[dict]) -> tuple[list[dict], dict]:
    """Return ``(records, stats)``; records are the ndjson lines."""
    resolver = ModResolver(mods, stats, descs, stat_records)

    records: list[dict] = []
    counts: dict[str, int] = {}
    dropped = 0
    disagreeing = 0
    for domain in sorted(POOL_GENERATIONS):
        for gen in POOL_GENERATIONS[domain]:
            rows = [m for m in mods
                    if m.get("Domain") == domain and m.get("GenerationType") == gen]
            implicit = gen in _IMPLICIT_GENERATIONS

            # Insertion order is the table's, so the ndjson comes out in the order GGG lists
            # the mods — stable between builds, and a readable diff.
            sets: dict[tuple, list[tuple[dict, list]]] = {}
            for m in rows:
                wordings = _wordings(resolver, m, implicit)
                if not wordings:
                    # Every stat this mod grants is hidden — a cosmetic footprint, monster-only
                    # behaviour. Nothing to word, so nothing to rate.
                    continue
                key = tuple((ref, tid) for ref, tid, _ in wordings)
                sets.setdefault(key, []).append((m, wordings))

            emitted = 0
            for wordings, group in sets.items():
                if _dropped([m["Id"] for m, _ in group], [ref for ref, _ in wordings]):
                    dropped += 1
                    continue
                if len({m.get("Name") or "" for m, _ in group}) > 1:
                    disagreeing += 1

                # The span over every tier in the set: the lowest floor and the highest
                # ceiling, which is what a regex written against a printed line is tested
                # against. A wording placing more than one number folds them together — none in
                # the pool as published does, and a union is the honest answer if one appears.
                bounds: dict[str, list[float]] = {}
                for _, ws in group:
                    for ref, _tid, pairs in ws:
                        for lo, hi in pairs:
                            b = bounds.get(ref)
                            bounds[ref] = [min(b[0], lo), max(b[1], hi)] if b else [lo, hi]

                rec = {"domain": domain, "gen": gen, "tiers": len(group),
                       "mods": [m["Id"] for m, _ in group],
                       "stats": [{"ref": ref,
                                  **({"trade": tid} if tid else {}),
                                  **({"min": bounds[ref][0], "max": bounds[ref][1]}
                                     if ref in bounds else {})}
                                 for ref, tid in wordings]}
                if name := _name([m for m, _ in group]):
                    rec["name"] = name
                records.append(rec)
                emitted += 1
            if emitted:
                counts[f"domain_{domain}_gen_{gen}"] = emitted

    return records, {
        "entries": len(records),
        "mod_rows": sum(r["tiers"] for r in records),
        "wordings": sum(len(r["stats"]) for r in records),
        # Expected and large: a map affix's wording is often one the trade site does not index
        # under any hash at all. It costs the entry nothing here — the pool is rated, not
        # searched — and it is the number that would move if the stat join ever drifted.
        "wordings_without_trade_id": sum(1 for r in records for s in r["stats"]
                                         if "trade" not in s),
        "never_printed_dropped": dropped,
        "sets_whose_rows_disagree_on_name": disagreeing,
        "stats_without_a_wording": resolver.counts["stats_without_description"],
        "wordings_without_a_stat_record": resolver.counts["wordings_without_stat_record"],
        "ambiguous_wordings": resolver.counts["ambiguous_wordings"],
        **counts,
    }
