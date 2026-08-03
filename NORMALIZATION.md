# Stat wording normalization

This is the normative description of the one algorithm that **two implementations must agree
on byte for byte**: `builder/ppcdata/normalize.py` here, and `src/data/stat_normalize.cpp` in
the PathOfPriceCheck client.

If they disagree, the client silently fails to match some mods — the worst failure mode the
project has, because a price check still returns a result, just the wrong one. That is why
every release ships `stat-normalization-vectors.ndjson`, and why the client has a test that
fails when it stops reproducing them.

## The problem

The clipboard gives a rendered mod line:

```
+42 to maximum Life
```

The lookup tables are keyed by the wording with its numbers replaced by `#`:

```
# to maximum Life
```

Producing that key, and the fallbacks to try when it misses, is normalization.

## Algorithm

### 1. Strip empty parentheses

Replace every literal `()` with nothing. GGG emits these occasionally.

### 2. Scan numeric tokens

A token starts at index `i` when:

* `s[i]` is `+`, `-` or a digit, **and**
* `i == 0` or `s[i-1]` is neither a digit nor `)`, **and**
* if `s[i]` is a sign, `s[i+1]` is a digit.

That lookbehind is load-bearing. Without it `1-30` splits into `1` and `-30` instead of `1`
and `30`, and every "Grants 1-30 Life" style wording normalizes wrongly.

Then consume digits, then optionally `.` followed by digits.

**The sign is part of the token.** `+42` is one token, so `+42 to maximum Life` becomes
`# to maximum Life` with no leading `+`. This is why the builder strips a `+` that
immediately precedes a `#` in GGG's trade text before joining: trade writes
`+# to maximum Life`, the game writes `# to maximum Life`.

### 3. Consume an optional advanced-mod-description range

If the next character is `(`, read to the matching `)`.

* The minimum takes **one arbitrary character**, then characters that are neither `)` nor
  `-`. That first-character exemption is what makes `(-20-10)` read as min `-20`, max `10`
  rather than splitting at the leading minus.
* If only a minimum is present, the maximum equals it.
* If either side fails to parse as a number, the bounds are **non-numeric**.

### 4. Enumerate candidates

Bit `i` of a mask set means token `i` stays `#`; a cleared bit is replaced with the token's
literal source text, bounds discarded. A kept token whose bounds are non-numeric emits
`#(min-max)` verbatim rather than a bare `#`.

Masks, in order, capped at 4 tokens:

| tokens | masks (most generic first) |
|---|---|
| 0 | `0000` |
| 1 | `0001`, `0000` |
| 2 | `0011`, `0001`, `0010`, `0000` |
| 3 | `0111`, `0110`, `0101`, `0011`, `0100`, `0010`, `0001` |
| 4 | `1111`, `1110`, `1101`, `1011`, `0111`, `1100`, `1010`, `1001`, `0110`, `0101`, `0011` |

The raw line is appended as a final fallback, and duplicates are removed while preserving
order.

**The order is load-bearing.** The generic form is tried first and wins wherever the data
has it. The literal forms exist for wordings that do not generalise — the singular
`1 Added Passive Skill is a Jewel Socket` only resolves because the plural generic form
`# Added Passive Skills are Jewel Sockets` is a different string and misses first.

Three tokens deliberately has no empty mask: a wording with three numbers and none of them
placeheld is not a form the data ever contains, and trying it only costs a lookup.

## Worked examples

| input | generic form |
|---|---|
| `+42 to maximum Life` | `# to maximum Life` |
| `23% increased Physical Damage` | `#% increased Physical Damage` |
| `Adds 5(4-6) to 12(10-14) Physical Damage` | `Adds # to # Physical Damage` |
| `+25(20-30)% to Cold Resistance` | `#% to Cold Resistance` |
| `Grants 1-30 Life per Enemy Hit` | `Grants #-# Life per Enemy Hit` |
| `0.5% of Physical Attack Damage Leeched as Life` | `#% of Physical Attack Damage Leeched as Life` |
| `No Physical Damage` | `No Physical Damage` |

## Conformance

`stat-normalization-vectors.ndjson`, one JSON object per line:

```json
{"line": "+42 to maximum Life",
 "generic": "# to maximum Life",
 "candidates": ["# to maximum Life", "+42 to maximum Life"]}
```

The client's `normalize_test` reads this file and must reproduce `generic` and `candidates`
exactly, in order.
