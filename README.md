# PathOfPriceCheck-Data

Builds the static Path of Exile game-data bundle that
[PathOfPriceCheck](https://github.com/JIRPOS/PathOfPriceCheck) downloads at runtime, and
publishes it as a versioned GitHub release.

The app ships **no game data in its binary**. It fetches `manifest.json` from the latest
release here, compares `data_version` with what it has cached, and downloads only when they
differ. That keeps app releases and data releases independent: a new league needs a data
build, not a new binary.

## What's in a release

| asset | what it is |
|---|---|
| `manifest.json` | schema/data version, game patch, per-file sha256 and size, absolute URLs |
| `en-items.ndjson` | base types, uniques, gems, divination cards, captured beasts — including each base's `Metadata/Items/…` id, whether it has ever traded on the in-game currency exchange, and each unique's artwork path |
| `en-items-name.index.bin` | fnv1a32 index, key `"{namespace}::{name}"` |
| `en-items-ref.index.bin` | fnv1a32 index, key `"{namespace}::{refName}"` |
| `en-items-base.index.bin` | fnv1a32 index over uniques only, key `"UNIQUE::{unique.base}"` — which uniques drop on a base, which is all an unidentified one states |
| `en-unique-mods.ndjson` | per unique: the mods it can roll, which of them come from a pool, and their ranges |
| `en-unique-mods-name.index.bin` | fnv1a32 index, key `"UNIQUE::{name}"` |
| `en-stats.ndjson` | clipboard wordings → trade stat hashes, with negate/fixed-value matchers |
| `en-stats-matcher.index.bin` | fnv1a32 index over every matcher string |
| `en-stats-ref.index.bin` | fnv1a32 index over the canonical wording |
| `item-classes.ndjson` | the clipboard's `Item Class:` line → trade category slug |
| `stat-normalization-vectors.ndjson` | conformance suite for the client's normalizer |
| `fnv1a-vectors.json` | hash agreement vectors |

Stable entry point, no GitHub API involved (which is 60 requests/hour unauthenticated):

```
https://github.com/JIRPOS/PathOfPriceCheck-Data/releases/latest/download/manifest.json
```

Assets are uncompressed. GitHub serves release assets from blob storage without transfer
compression, so this is a real ~4 MB download — but it happens once per patch, in the
background. `manifest.json` carries a per-file `encoding` field so compression can be added
later as something the client either understands or refuses, rather than as a format break.

## Where the data comes from

Two sources for everything except the unique-mod dataset and the exchange flag, joined on the
normalized wording:

* **The game's own files.** [`pathofexile-dat`](https://github.com/SnosMe/poe-dat-viewer)
  downloads GGG's `.datc64` bundles straight from the patch CDN and decodes them with
  [dat-schema](https://github.com/poe-tool-dev/dat-schema). No game install is needed, and
  because it uses `ooz-wasm` for Oodle decompression there is no native blob either — it
  runs on a stock CI runner with only Node.
* **GGG's trade API** (`/api/trade/data/{stats,items,static,filters}`) for the stat hashes
  a query has to be built from.

Neither alone is enough. The trade API has no wording for the "reduced" phrasing of a stat
it indexes as "increased", and no entry at all for fixed-value wordings like
`No Physical Damage`; those come from `stat_descriptions.txt`. The game files have no trade
hashes.

The join key is the `#`-placeholder form of the wording — see
[NORMALIZATION.md](NORMALIZATION.md), which the client reimplements and is tested against
the vectors shipped in every release.

### The fourth source: which items trade on the currency exchange

`en-items.ndjson` carries `exchange: true` on every base that has **ever** appeared in a market on
GGG's in-game currency exchange. That is one boolean and no new asset, but it answers a question
nothing else can.

The app prices a stack of currency, a scarab, an essence or a card off
[the exchange feed](https://web.poecdn.com/api/currency-exchange) rather than off the trade site,
because an exchange market is not a listing. That feed is published as **hourly digests**, so it can
only ever say whether an item traded *in the last hour* — and for a thin item, a Weeping Essence of
Greed, no trades in a given hour is the normal case rather than an answer. Without this flag the
app could not tell "this is not traded on the exchange" from "nobody traded one recently", and
since poe.ninja has no price for such an item either, the price check came back saying nothing at
all. "Has this item ever traded there" is a property of the item, so it belongs in the bundle.

`sources/exchange.py` crawls the feed forward from a cursor committed to the repo at
`builder/state/exchange-seen.json` (`{"last_hour": …, "ids": [...]}`). Committed rather than cached:
an Actions cache is evictable, and a silent eviction would restart a 17.8k-hour backfill inside a
job that budgets for six requests. The diff is also the review surface for which items newly
started trading. Two rules keep it honest — never advance past an hour that was not actually read,
and treat an hour still empty several hours after it ended as a real gap in GGG's history rather
than waiting for it forever.

The feed is public, unauthenticated and on the CDN, so there is no rate-limit policy to honour;
what stands in for one is that a published hour never changes (`max-age` is a year), so nothing is
ever re-fetched. The steady-state cost is six requests per build. The one-off backfill from
Settlers launch is run locally, once — `python -m ppcdata crawl-exchange --backfill-from 1722027600`
— and is resumable, because 17.8k requests will be interrupted.

The manifest carries `source.exchange_items`, the size of the set. That is what lets the client
tell a bundle published before this dataset from one where a missing flag genuinely means the item
does not trade there; an item-level boolean cannot say so on its own.

### A unique's artwork

`en-items.ndjson` carries `art` on every unique the game has a picture for — the path GGG's own
CDN serves it at, so the client fetches
`https://web.poecdn.com/image/Art/2DItems/Armours/Gloves/Hrimsorrow.png` (with `?w=&h=&scale=1`
where it knows the base's inventory size) and no third party is involved.

It is here because an **unidentified** unique states only its base, and which of that base's
uniques it is can only be answered by looking at the item: a Prismatic Jewel is seven different
uniques and a Cobalt Jewel fifty-four. A picker that only names them is a list of words for an
item the player recognises by its picture.

A unique is not a row in `BaseItemTypes` — it is a name, a base and a mod list assembled when the
item drops — so the only join that reaches a picture is `UniqueStashLayout`, where `Words.Text`
is the display name the client prints and the clipboard repeats. Alternate-art rows are skipped:
they are the foil and race-reward variants of the same unique, and one of those in place of the
ordinary art shows the player something that does not look like the item in their stash. **1416
of trade's 1526 uniques** have a row; the rest — sanctum relics, the Harbinger pieces, a few
renamed out of the client's word list — get nothing, because guessing a path from the name would
be a 404 per item. Two uniques sharing one picture is not a bug, and the game data says so
outright: Hrimburn and Hrimsorrow both point at `Hrimsorrow.dds`.

### The third source, and why there has to be one

`en-unique-mods.ndjson` answers "which mods can *this* unique roll, and which of them vary".
A Watcher's Eye picks two or three mods out of 93; Ralakesh's Impatience rolls one of three
charge modifiers, each `1..1`. The clipboard prints such a mod exactly like a fixed one, and
the difference is routinely the difference between vendor trash and several divines.

**That grouping is not in the game client.** Verified against patch 3.29.1.2.2 by enumerating
all 1,205,200 paths in the bundle index: the only per-unique tables are `UniqueStashLayout`,
`UniqueMaps`, `UniqueJewelLimits` and `UniqueUpgradesClient` — names, art, stash placement and
limits — and `metadata/items/**` holds 397 base-class `.it` templates plus art directories.
Mod-to-unique assignment is server-side, which is also why an unidentified unique shows only
its base. `Mods.dat` *does* carry all 15,886 unique-generation mods with their stats and
ranges, so only the grouping is missing, and mod ids embed the item's name for just 31 of
1,383 uniques — a naming heuristic is not an option.

So the grouping comes from **[poewiki](https://www.poewiki.net)'s `item_mods` cargo table**,
which publishes GGG's own mod ids per unique page with `is_random` / `is_implicit` flags. It
supplies an **id → id edge list and nothing else**: 9,313 rows, of which every mod id resolves
in our own `Mods.dat` extraction. Every number in the emitted dataset — stats, ranges, trade
hashes — is still client- and trade-API-derived, reached by exactly the join described above.
Wiki content is CC BY-NC 3.0; see [DATA-LICENSE.md](DATA-LICENSE.md).

One record per unique, keyed `UNIQUE::{name}`:

```json
{"base": "Prismatic Jewel", "name": "Watcher's Eye",
 "fixed": [{"mod": "IncreasedEnergyShieldPercentUnique__2_",
            "filters": [{"range": [[4, 6]], "ref": "#% increased maximum Energy Shield",
                         "tradeId": "explicit.stat_2482852589"}]}],
 "pools": [{"count": [2, 3], "hint": "Two or Three random aura modifiers",
            "mods": [{"mod": "AngerIncreasedFireDamage",
                      "filters": [{"range": [[40, 60]],
                                   "ref": "#% increased Fire Damage while affected by Anger",
                                   "tradeId": "explicit.stat_3337107517"}]}]}]}
```

`fixed` is every mod the item always has, `pools` the ones it picks from, `unlisted` a pool the
wiki states in prose but does not enumerate. `range` has one `[min, max]` per stat the wording
covers ("Adds # to # Fire Damage" has two) **in displayed units** — `Mods.dat` stores hundredths
and milliseconds raw, and the record's `dp` is already applied. A filter with no `tradeId` is
real and displayable but not searchable. `implicit: true` appears on an entry or a pool when the
mod is an implicit. The consumer-side contract is
[UNIQUE-MODS.md](https://github.com/JIRPOS/PathOfPriceCheck/blob/master/UNIQUE-MODS.md) in the
app repo.

## Building locally

Needs Python 3.11+ and Node.

```sh
cd builder
python -m ppcdata build --out ../out          # downloads from the CDN; first run is slow
python -m ppcdata verify --out ../out         # sha256s, index sortedness, offset sanity
python -m ppcdata build --out ../out --skip-extract   # reuse the extraction in .work/
python -m ppcdata build --out ../out --reuse-wiki     # reuse the cached poewiki mapping too
```

`--allow-stale-wiki` (which CI passes) falls back to the cached mapping when the wiki fetch
fails instead of failing the build; `--reuse-wiki` skips the fetch outright.
`--skip-exchange-crawl` uses the committed exchange cursor without advancing it.

The one-off currency-exchange backfill, run once and locally — not in CI:

```sh
python -m ppcdata crawl-exchange --backfill-from 1722027600
```

Roughly 17.8k requests and a couple of hours, resumable at any point, and about 100 KB of
committed state at the end. Afterwards the build's own crawl only has the six hours since the
last one to catch up on.

The build is deterministic: two runs produce byte-identical data files. Only
`manifest.json` differs, because it carries timestamps.

## Publishing

`.github/workflows/build.yml` runs every 6 hours and on demand. It builds unconditionally
and then compares **output** hashes against the previous release — inputs churn without
outputs changing, so comparing outputs is the honest gate for "is a new release warranted".
When nothing changed it publishes nothing.

A failed build publishes nothing and the previous release keeps serving. That is deliberate:
a partial bundle is worse than a stale one.

Each run also advances the currency-exchange cursor by the six hours since the last one and
commits `builder/state/exchange-seen.json` back, whether or not a bundle is published — the
hours were crawled either way. A feed outage leaves the cursor where it was and the previous
flags keep serving, the same way `--allow-stale-wiki` degrades the unique-mod dataset rather
than the whole build.

## Caveats

* `constants/known_stats.py` holds the handful of facts neither source states — chiefly
  which direction of a roll is desirable. The build **fails** if an entry there matches no
  stat, so the table cannot rot silently.
* Roughly 30% of trade wordings have no game-side description and fall back to the trade
  text as their single matcher. That is correct for namespaces the client never renders
  (crucible mod text, veiled affix names, gem support text) and a known gap elsewhere.
* Icons are stored as CDN URL strings. No game art is redistributed.
* **English only.** Every asset is language-prefixed and `manifest.json` declares a `languages`
  list, so the format has always anticipated more — but `LANG` is `"en"`, only the English
  `stat_descriptions.txt` files are fetched, and no other language is built. Adding one means
  pulling GGG's localised description files and emitting a second set of assets; nothing in the
  schema has to change for it.
* The wiki lags a league launch by days. A new unique simply has no `en-unique-mods.ndjson`
  record until it does, and the app must degrade to "no pool data" rather than to a wrong
  filter. The wiki also sits behind a bot challenge that answers HTML instead of JSON: CI
  passes `--allow-stale-wiki` so that costs the dataset its freshness, not the whole bundle.
* Within that dataset, 470 wordings resolve to two different trade ids and 695 to none at all;
  both are emitted with their wording and range but **no `tradeId`**, so a pool list still
  matches the count its hint states. 50 unique-rarity wiki pages (Sanctum relics, tattoos) are
  dropped because the trade API does not list them, and 1,413 uniques get a record.
* Forbidden Flame / Forbidden Flesh are a known gap: their one mod grants a hidden stat, and
  trade searches them through an *option* stat the join does not reach. They get a record with
  no mods rather than a wrong one.
* The exchange flag is **evidence of trade, never proof of its absence**. An item that has simply
  never been traded in any hour since Settlers launch is indistinguishable from one that cannot be
  traded there, and both come out unflagged. That is the safe direction: an unflagged item keeps
  its trade search, and the flag only ever removes a search that could not have worked.
* A handful of ids the feed names match no base. Expected and non-zero — the feed covers private
  leagues and items the trade API does not list, and a base retired since it last traded keeps its
  id in the set — so the build reports the count rather than failing on it. A number that jumps is
  the signal that the id join has drifted.

## Credits

* [awakened-poe-trade](https://github.com/SnosMe/awakened-poe-trade) (MIT) — the ndjson
  schema and the matching algorithm this reproduces
* [the Path of Exile Wiki](https://www.poewiki.net) (CC BY-NC 3.0) — the `item_mods` cargo
  table, which is where `en-unique-mods.ndjson` gets its unique → mod-id mapping
* [poe-dat-viewer / pathofexile-dat](https://github.com/SnosMe/poe-dat-viewer)
* [dat-schema](https://github.com/poe-tool-dev/dat-schema) and
  [latest-patch-version](https://github.com/poe-tool-dev/latest-patch-version)
* [Exiled-Exchange-2](https://github.com/Kvan7/Exiled-Exchange-2) — the public reference for
  the game-data/trade-API merge

See [DATA-LICENSE.md](DATA-LICENSE.md) for the status of the generated data.
