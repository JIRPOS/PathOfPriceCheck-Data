"""Placeholder normalization — the one algorithm both implementations must agree on.

A clipboard mod line is turned into a series of lookup candidates by replacing its numbers
with '#'. The C++ client reimplements this byte for byte; ``NORMALIZATION.md`` is the
normative description and ``stat-normalization-vectors.ndjson`` is the conformance suite
generated from this module. Change one, regenerate the other.
"""

from __future__ import annotations

from dataclasses import dataclass

# Which token indices stay '#', most-generic first. The order is load-bearing: the generic
# form is tried first and wins when the data has it, so a literal wording only takes effect
# when the generic one is absent.
CANDIDATE_MASKS: list[list[int]] = [
    [0b0000],
    [0b0001, 0b0000],
    [0b0011, 0b0001, 0b0010, 0b0000],
    [0b0111, 0b0110, 0b0101, 0b0011, 0b0100, 0b0010, 0b0001],
    [0b1111, 0b1110, 0b1101, 0b1011, 0b0111, 0b1100, 0b1010, 0b1001, 0b0110, 0b0101, 0b0011],
]

MAX_TOKENS = 4


@dataclass
class NumberToken:
    """A numeric token plus the advanced-mod-description range that may follow it.

    ``+25(20-30)%`` yields value 25, bounds 20..30, spanning ``+25(20-30)``.
    """

    begin: int
    value_end: int  # end of the number itself, excluding any "(...)"
    end: int  # end of the whole token, including "(...)"
    value: float
    decimals: int
    has_bounds: bool = False
    numeric_bounds: bool = False
    bound_min: float = 0.0
    bound_max: float = 0.0
    bound_text: str = ""  # verbatim "(min-max)" when the bounds are not numeric


def _is_digit(c: str) -> bool:
    return "0" <= c <= "9"


def _as_float(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def strip_empty_parens(line: str) -> str:
    """GGG sometimes emits a bare '()'. Remove it before anything else looks at the text."""
    return line.replace("()", "")


def scan_numbers(line: str) -> list[NumberToken]:
    """Find every numeric token, in order.

    A token starts at a '+', '-' or digit that is *not* preceded by a digit or ')'. That
    lookbehind is what keeps "1-30" from splitting into two tokens, and what makes the sign
    part of the number rather than a separate character.
    """
    out: list[NumberToken] = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        signed = c in "+-"
        if not (signed or _is_digit(c)):
            i += 1
            continue
        if signed and (i + 1 >= n or not _is_digit(line[i + 1])):
            i += 1
            continue
        if i > 0 and (_is_digit(line[i - 1]) or line[i - 1] == ")"):
            i += 1
            continue

        begin = i
        if signed:
            i += 1
        while i < n and _is_digit(line[i]):
            i += 1
        decimals = 0
        if i + 1 < n and line[i] == "." and _is_digit(line[i + 1]):
            i += 1
            start_frac = i
            while i < n and _is_digit(line[i]):
                i += 1
            decimals = i - start_frac
        value_end = i
        value = float(line[begin:value_end])

        tok = NumberToken(begin=begin, value_end=value_end, end=value_end,
                          value=value, decimals=decimals)

        # Optional advanced-mod-description range: "(min-max)" or "(min)".
        if i < n and line[i] == "(":
            close = line.find(")", i)
            if close != -1:
                inner = line[i + 1 : close]
                # min takes one arbitrary character, then characters that are neither ')'
                # nor '-'. That first-character exemption is what lets "(-20-10)" read as
                # min "-20", max "10" instead of splitting at the leading minus.
                lo_txt, hi_txt = inner, inner
                if len(inner) > 1:
                    sep = inner.find("-", 1)
                    if sep != -1:
                        lo_txt, hi_txt = inner[:sep], inner[sep + 1 :]
                lo, hi = _as_float(lo_txt), _as_float(hi_txt)
                tok.has_bounds = True
                tok.end = close + 1
                tok.bound_text = line[value_end : close + 1]
                if lo is not None and hi is not None:
                    tok.numeric_bounds = True
                    tok.bound_min, tok.bound_max = lo, hi
                    if any("." in t for t in (lo_txt, hi_txt)):
                        tok.decimals = max(
                            tok.decimals,
                            max(len(t.split(".")[1]) for t in (lo_txt, hi_txt) if "." in t),
                        )
                i = close + 1

        out.append(tok)
    return out


def apply_candidate(line: str, tokens: list[NumberToken], keep: int) -> str:
    """Render one candidate. Bit i of ``keep`` set means token i stays '#'."""
    parts: list[str] = []
    cursor = 0
    for idx, t in enumerate(tokens):
        parts.append(line[cursor : t.begin])
        if keep & (1 << idx):
            # A kept token whose bounds are non-numeric keeps them verbatim; the game
            # renders those as part of the wording, not as a roll.
            parts.append("#" + (t.bound_text if t.has_bounds and not t.numeric_bounds else ""))
        else:
            parts.append(line[t.begin : t.value_end])
        cursor = t.end
    parts.append(line[cursor:])
    return "".join(parts)


def candidates(line: str) -> list[str]:
    """Every lookup candidate for ``line``, most-generic first, duplicates removed.

    The raw line is always the last resort, so a wording with no numbers at all still
    resolves.
    """
    text = strip_empty_parens(line)
    tokens = scan_numbers(text)[:MAX_TOKENS]
    out: list[str] = []
    for keep in CANDIDATE_MASKS[len(tokens)]:
        c = apply_candidate(text, tokens, keep)
        if c not in out:
            out.append(c)
    if text not in out:
        out.append(text)
    return out


def placeholder_form(line: str) -> str:
    """The fully-generic candidate: every number replaced by '#'.

    This is the join key between GGG's trade text and the game's own stat descriptions.
    """
    text = strip_empty_parens(line)
    tokens = scan_numbers(text)
    return apply_candidate(text, tokens, (1 << len(tokens)) - 1)
