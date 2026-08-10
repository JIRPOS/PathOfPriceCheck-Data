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

# "{0}", "{1}", "{0:+d}", "{:+d}", "{0:d}" — every format placeholder becomes '#'. The digits
# are the 0-based index of the stat that fills it, and the text is free to use them out of
# order ("... by level {2} {1}"), so they are kept rather than discarded.
_PLACEHOLDER = re.compile(r"\{(\d*)(?::[^}]*)?\}")
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')

# A trailing "display_indexable_skill 2" says the stat in that slot is a **row number** in a
# client table, not a number to print: the game renders the name it finds there. The argument
# is the stat's 1-based position in the block's own list. Two tables, three spellings.
INDEXABLE_TABLES = {
    "display_indexable_skill": "skill",
    "display_indexable_support": "support",
    "display_indexable_non_active_support": "support",
}


@dataclass
class Variant:
    ranges: list[str]
    text: str  # '#'-placeholder form
    negate: bool = False
    fixed_value: float | None = None  # wording implies a roll but shows no number
    modifiers: list[str] = field(default_factory=list)
    #: The 0-based stat index behind each '#', in the order the text prints them.
    placeholders: list[int] = field(default_factory=list)
    #: ``(table, 0-based stat index)`` when one of this wording's values is a name.
    indexable: tuple[str, int] | None = None


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
    # `\n` is a real line break, and a modifier that spans lines is one wording: the trade text
    # carries the break itself, so leaving the escape undecoded means no multi-line wording ever
    # joins to its trade record. That is 568 variants, and it costs them their negate and
    # fixed-value forms in stats.ndjson and their trade id in unique-mods.ndjson.
    raw_text = m.group(1).replace('\\"', '"').replace("\\n", "\n")

    placeholders: list[int] = []

    def _placehold(pm: re.Match) -> str:
        # "{}" carries no index and means "the next stat", which is what its position is.
        placeholders.append(int(pm.group(1)) if pm.group(1) else len(placeholders))
        return "#"

    text = _PLACEHOLDER.sub(_placehold, raw_text).strip()

    tail = line[m.end() :].split()
    negate = False
    indexable = None
    for i, tok in enumerate(tail):
        if tok == "negate" and i + 1 < len(tail) and tail[i + 1] not in ("0",):
            negate = True
        if tok in INDEXABLE_TABLES and i + 1 < len(tail) and tail[i + 1].isdigit():
            indexable = (INDEXABLE_TABLES[tok], int(tail[i + 1]) - 1)

    # A wording with no '#' still stands for a roll; it comes from the primary stat's range.
    fixed = None
    if "#" not in text and ranges:
        fixed = _implied_value(ranges[0])

    return Variant(ranges=ranges, text=text, negate=negate, fixed_value=fixed, modifiers=tail,
                   placeholders=placeholders, indexable=indexable)


def pinned_value(spec: str) -> int | None:
    """The one stat value a range spec pins its variant to, or None.

    A description that renders a different wording per value of an index stat states that
    value as the whole range — ``1``, ``2``, ``3``. Anything carrying ``#`` or ``|`` spans
    values instead and pins none.
    """
    spec = spec.strip()
    if not spec or "#" in spec or "|" in spec:
        return None
    try:
        return int(spec)
    except ValueError:
        return None


def spec_accepts(spec: str, lo: int, hi: int) -> bool:
    """Whether a variant's range spec covers a mod's whole ``lo..hi`` for that stat.

    This is how the ``+`` and ``-`` wordings of one description are told apart: they differ
    only by ``1|#`` against ``#|-1``.
    """
    spec = spec.strip()
    if not spec or spec == "#":
        return True
    try:
        if "|" not in spec:
            return lo == hi == int(spec)
        a, b = spec.split("|", 1)
        if a not in ("#", "") and lo < int(a):
            return False
        if b not in ("#", "") and hi > int(b):
            return False
    except ValueError:
        return False
    return True


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
