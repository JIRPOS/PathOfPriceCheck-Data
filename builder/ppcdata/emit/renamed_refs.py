"""``renamed-refs.json`` — reworded pool refs, so a verdict on the old wording finds the new one.

Unprefixed: a ``ref`` is the stat record's identity, not the client's printed line.
"""

from __future__ import annotations


def _refs_by_mod(pool_records: list[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in pool_records:
        refs = {s["ref"] for s in r["stats"]}
        for mid in r["mods"]:
            out.setdefault(mid, set()).update(refs)
    return out


def detect(old_pool: list[dict], new_pool: list[dict]) -> dict[str, str]:
    """``{old ref: new ref}`` for wordings that look reworded between two pools.

    Keyed on mod ids present in both. A removed ref pairs with the one ref added on every mod
    that lost it and on no mod that kept it — so a line a league adds everywhere (3.30's Atlas
    Drops) is never mistaken for a rename. Anything less clear-cut is not proposed.
    """
    old, new = _refs_by_mod(old_pool), _refs_by_mod(new_pool)
    lost_by: dict[str, list[str]] = {}
    added: dict[str, set[str]] = {}
    for mid in old.keys() & new.keys():
        added[mid] = new[mid] - old[mid]
        for ref in old[mid] - new[mid]:
            lost_by.setdefault(ref, []).append(mid)
    out = {}
    for ref, mids in lost_by.items():
        common = set.intersection(*(added[m] for m in mids))
        elsewhere = set().union(*(a for m, a in added.items() if m not in mids))
        if len(common - elsewhere) == 1:
            out[ref] = next(iter(common - elsewhere))
    return out


def build(renamed: dict[str, str], live_refs: set[str]) -> tuple[dict, list[str]]:
    """The emitted document, with chains collapsed, and why any entry was left out.

    An entry the pool contradicts is dropped rather than failing the build: a league that
    retires a wording must not hold up the data release that league needs.
    """
    out, dropped = {}, []
    for was in renamed:
        now, seen = was, {was}
        while now in renamed:
            now = renamed[now]
            if now in seen:
                raise ValueError(f"renamed refs loop through {now!r}")
            seen.add(now)
        # Verdicts are not keyed by domain, so a wording still live anywhere would hand that
        # modifier's verdicts to another.
        if was in live_refs:
            dropped.append(f"{was!r} is a live wording again")
        elif now not in live_refs:
            dropped.append(f"{was!r} -> {now!r}: no current wording")
        else:
            out[was] = now
    return {"renamed": dict(sorted(out.items()))}, dropped
