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
`# to maximum Life` with no leading `+`.

This is why the builder folds a sign that immediately precedes a `#` **on both sides**, and
the second half of that was missing for a long time:

* *Trade's* wordings are folded before joining — trade writes `+# to maximum Life`, the game
  writes `# to maximum Life`, and the two have to meet.
* *The game's own* wordings are folded before being **emitted**. GGG spells the sign two ways
  and only one of them disappears by itself: `{0:+d} to maximum Life` hides it in the format
  spec, while `+{0}% Monster Chaos Resistance` writes it as literal text that survives into the
  wording. Both render identically in game, and the algorithm above cannot tell them apart — it
  takes the sign into the number either way. So a wording emitted as `+#%` is indexed under a
  key no clipboard line can produce, and the stat is not mispriced but simply never found. 47
  matcher strings over 34 records shipped that way, among them every `+#% Monster …
  Resistance`, which is the whole family a map rolls.

Where folding makes a stat's `+#` and `-#` wordings identical, the **plain** one is kept and
the `negate` twin dropped: with the sign folded they say the same thing, and negating on top of
a number that already carries its own sign would turn a printed `-40` into `+40`.

### 3. Consume an optional advanced-mod-description range

If the next character is `(`, read to the matching `)`.

* The minimum takes **one arbitrary character**, then characters that are neither `)` nor
  `-`. That first-character exemption is what makes `(-20-10)` read as min `-20`, max `10`
  rather than splitting at the leading minus.
* If only a minimum is present, the maximum equals it.
* If either side fails to parse as a number, the bounds are **non-numeric**.

### 4. Drop named ranges

A modifier can roll over a **list** rather than over an interval, and the game prints that
range the same way it prints a numeric one:

```
Maximum number of Sentinels of Purity (Animated Weapons-Holy Armaments) is Doubled
```

The roll is a minion skill gem and the parenthesis is the first and last of the list, exactly
as `(50-100)` is the first and last of an interval. Step 2 cannot see it — there is no numeric
token in front of it to carry the bounds — and trade indexes one wording per option, spelling
the name out. So the range is **dropped**, not placeheld.

A group qualifies when all of:

* it does not follow a digit or `)` — a numeric token's own range belongs to that token,
  numeric bounds or not;
* its interior splits at a `-` found from index 1, with a non-empty half either side;
* **neither** half parses as a number.

`(Blood-Filled Vessel)` in `Unique Monsters (Blood-Filled Vessel): #` qualifies too, which is
why this produces an *additional* candidate rather than replacing the line — see step 5.

### 5. Enumerate candidates

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

When step 4 changed the line, the whole enumeration runs a **second time** on the stripped
form and its candidates are appended after the first set. Stripping only ever adds candidates,
so a wording whose parenthesis is genuinely part of it resolves as printed and never reaches
them:

```text
Maximum number of Sentinels of Purity (Animated Weapons-Holy Armaments) is Doubled
  → "Maximum number of Sentinels of Purity (Animated Weapons-Holy Armaments) is Doubled"
    "Maximum number of Sentinels of Purity is Doubled"
```

`placeholder_form` is **not** affected: it is the builder's join key between two sources that
are already in `#` form, and neither of them prints a range at all.

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
