"""Parser for the game's ``Metadata/StatDescriptions/stat_descriptions.txt``.

This is where the wordings the trade API cannot give us come from: the "reduced" phrasing of
a stat indexed as "increased", fixed-value forms like "No Physical Damage", and the decimal
placement. Verified against the trade API: it carries neither the negate wordings nor the
fixed-value ones, so this file is not optional.

Format (UTF-16LE, CRLF), one block per description::

    description
        1 physical_damage_+%                      <- stat-id count, then the ids
        2                                         <- variant count
            1|# "{0}% increased Global Physical Damage"
            #|-1 "{0}% reduced Global Physical Damage" negate 1
        lang "Russian"                            <- other languages follow; we stop here
        ...

One range spec per stat id precedes the quoted text. Trailing words are modifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# "{0}", "{1}", "{0:+d}", "{:+d}", "{0:d}" — every format placeholder becomes '#'.
_PLACEHOLDER = re.compile(r"\{\d*(?::[^}]*)?\}")
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


@dataclass
class Variant:
    ranges: list[str]
    text: str  # '#'-placeholder form
    negate: bool = False
    fixed_value: float | None = None  # wording implies a roll but shows no number
    modifiers: list[str] = field(default_factory=list)


@dataclass
class Description:
    stat_ids: list[str]
    variants: list[Variant]


def _decode(path: str) -> str:
    raw = open(path, "rb").read()
    # The extractor writes UTF-16LE with a BOM; some files come back UTF-8.
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-16-le", errors="replace")


def _implied_value(spec: str) -> float | None:
    """The roll a wording with no visible number implies.

    "0|0" and "1" pin a value outright. "#|-100" is open-ended but its finite bound is the
    roll the wording stands for — that is where "No Physical Damage" gets -100.
    """
    spec = spec.strip()
    if spec in ("#", ""):
        return None
    if "|" not in spec:
        try:
            return float(spec)
        except ValueError:
            return None
    lo, hi = spec.split("|", 1)
    if lo == hi:
        try:
            return float(lo)
        except ValueError:
            return None
    for bound in (hi, lo):  # prefer the upper bound: "#|-100" means "as low as -100"
        if bound not in ("#", ""):
            try:
                return float(bound)
            except ValueError:
                continue
    return None


def _parse_variant(line: str, n_stats: int) -> Variant | None:
    m = _QUOTED.search(line)
    if not m:
        return None
    head = line[: m.start()].split()
    ranges = head[:n_stats] if len(head) >= n_stats else head
    raw_text = m.group(1).replace('\\"', '"')
    text = _PLACEHOLDER.sub("#", raw_text).strip()

    tail = line[m.end() :].split()
    negate = False
    for i, tok in enumerate(tail):
        if tok == "negate" and i + 1 < len(tail) and tail[i + 1] not in ("0",):
            negate = True

    # A wording with no '#' still stands for a roll; it comes from the primary stat's range.
    fixed = None
    if "#" not in text and ranges:
        fixed = _implied_value(ranges[0])

    return Variant(ranges=ranges, text=text, negate=negate, fixed_value=fixed, modifiers=tail)


def parse(path: str) -> list[Description]:
    """Every English description block, in file order."""
    text = _decode(path)
    lines = text.split("\n")
    out: list[Description] = []

    i, n = 0, len(lines)
    while i < n:
        if lines[i].strip() != "description":
            i += 1
            continue
        i += 1
        if i >= n:
            break

        # "<count> <id> [<id>...]"
        head = lines[i].strip().split()
        i += 1
        if not head or not head[0].isdigit():
            continue
        n_stats = int(head[0])
        stat_ids = head[1 : 1 + n_stats]
        if len(stat_ids) != n_stats:
            continue

        if i >= n or not lines[i].strip().isdigit():
            continue
        n_variants = int(lines[i].strip())
        i += 1

        variants: list[Variant] = []
        for _ in range(n_variants):
            if i >= n:
                break
            v = _parse_variant(lines[i], n_stats)
            i += 1
            if v:
                variants.append(v)

        if variants:
            out.append(Description(stat_ids=stat_ids, variants=variants))

        # Skip the other languages: everything until the next top-level "description".
        while i < n and lines[i].strip() != "description":
            i += 1

    return out


def primary_variant(d: Description) -> Variant:
    """The wording that stands for the stat itself.

    The first variant is often a special case rather than the general one — the block for
    ``local_physical_damage_+%`` opens with three "No Physical Damage" forms before
    "#% increased Physical Damage". The general wording is the first that shows a number and
    is not a negation.
    """
    for v in d.variants:
        if "#" in v.text and not v.negate:
            return v
    return d.variants[0]


def by_english_text(descs: list[Description]) -> dict[str, Description]:
    """Index descriptions by *every* wording they can render, not just the primary one.

    Indexing only the primary text loses the negate and fixed-value wordings, which are the
    whole reason this file is parsed.
    """
    out: dict[str, Description] = {}
    for d in descs:
        for v in d.variants:
            # First writer wins: the canonical block precedes its skill-specific overrides.
            out.setdefault(v.text, d)
    return out
