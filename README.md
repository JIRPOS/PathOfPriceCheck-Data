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
| `en-items.ndjson` | base types, uniques, gems, divination cards, captured beasts |
| `en-items-name.index.bin` | fnv1a32 index, key `"{namespace}::{name}"` |
| `en-items-ref.index.bin` | fnv1a32 index, key `"{namespace}::{refName}"` |
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

Two sources, joined on the normalized wording:

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

## Building locally

Needs Python 3.11+ and Node.

```sh
cd builder
python -m ppcdata build --out ../out          # downloads from the CDN; first run is slow
python -m ppcdata verify --out ../out         # sha256s, index sortedness, offset sanity
python -m ppcdata build --out ../out --skip-extract   # reuse the extraction in .work/
```

The build is deterministic: two runs produce byte-identical data files. Only
`manifest.json` differs, because it carries timestamps.

## Publishing

`.github/workflows/build.yml` runs every 6 hours and on demand. It builds unconditionally
and then compares **output** hashes against the previous release — inputs churn without
outputs changing, so comparing outputs is the honest gate for "is a new release warranted".
When nothing changed it publishes nothing.

A failed build publishes nothing and the previous release keeps serving. That is deliberate:
a partial bundle is worse than a stale one.

## Caveats

* `constants/known_stats.py` holds the handful of facts neither source states — chiefly
  which direction of a roll is desirable. The build **fails** if an entry there matches no
  stat, so the table cannot rot silently.
* Roughly 30% of trade wordings have no game-side description and fall back to the trade
  text as their single matcher. That is correct for namespaces the client never renders
  (crucible mod text, veiled affix names, gem support text) and a known gap elsewhere.
* Icons are stored as CDN URL strings. No game art is redistributed.

## Credits

* [awakened-poe-trade](https://github.com/SnosMe/awakened-poe-trade) (MIT) — the ndjson
  schema and the matching algorithm this reproduces
* [poe-dat-viewer / pathofexile-dat](https://github.com/SnosMe/poe-dat-viewer)
* [dat-schema](https://github.com/poe-tool-dev/dat-schema) and
  [latest-patch-version](https://github.com/poe-tool-dev/latest-patch-version)
* [Exiled-Exchange-2](https://github.com/Kvan7/Exiled-Exchange-2) — the public reference for
  the game-data/trade-API merge

See [DATA-LICENSE.md](DATA-LICENSE.md) for the status of the generated data.
