"""ppcdata — build the PathOfPriceCheck game-data bundle.

    python -m ppcdata build   --out out/ [--patch X] [--workdir .work/]
    python -m ppcdata verify  --out out/
    python -m ppcdata vectors --out out/
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

from . import normalize, statdesc
from .constants.categories import TRADE_CATEGORY_BY_CLASS_ID
from .constants.known_stats import BETTER_MINUS_ONE, TRADE_INVERTED
from .emit import index as emit_index
from .emit import items as emit_items
from .emit import manifest as emit_manifest
from .emit import stats as emit_stats
from .sources import game_bundle, patch as patch_src, trade_api

LANG = "en"


def _write_ndjson(path: Path, records: list[dict]) -> list[tuple[str, int]]:
    """Write one JSON object per line; return (line_text, byte_offset) for indexing.

    Offsets are byte positions of each line's first character, which is what the index
    stores and what the client seeks to.
    """
    offsets: list[tuple[str, int]] = []
    with path.open("wb") as f:
        pos = 0
        for r in records:
            line = json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            blob = line.encode("utf-8") + b"\n"
            offsets.append((line, pos))
            f.write(blob)
            pos += len(blob)
    return offsets


def _index_file(path: Path, pairs: list[tuple[str, int]], label: str) -> int:
    blob, collisions = emit_index.build(pairs)
    path.write_bytes(blob)
    if collisions:
        print(f"  {label}: {collisions} hash collisions (reader walks the run)")
    return collisions


def cmd_build(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for p in out.iterdir():
        if p.is_file():
            p.unlink()
    work = Path(args.workdir).resolve()

    game_patch = args.patch or patch_src.latest()
    print(f"patch {game_patch}")

    print("fetching trade API ...")
    trade = trade_api.fetch_all()
    trade_stats, stats_lm = trade["stats"]
    trade_items, items_lm = trade["items"]

    if args.skip_extract and game_bundle.stat_descriptions_path(work).exists():
        print(f"reusing extracted game data in {work}")
    else:
        print(f"extracting game data into {work} (downloads from the patch CDN) ...")
        game_bundle.extract(work, game_patch)

    print("parsing stat descriptions ...")
    descs = []
    for p in game_bundle.description_paths(work):
        part = statdesc.parse(str(p))
        print(f"  {p.name.rsplit('@', 1)[-1]}: {len(part)}")
        descs.extend(part)
    print(f"  {len(descs)} descriptions total")

    classes = game_bundle.table(work, "ItemClasses")
    bases = game_bundle.table(work, "BaseItemTypes")
    armour = game_bundle.table(work, "ArmourTypes")
    tags = game_bundle.table(work, "Tags")

    print("building stats.ndjson ...")
    stat_records, sstats = emit_stats.build(trade_stats, descs, {
        ref: -1 for ref in BETTER_MINUS_ONE}, TRADE_INVERTED)
    stale = list(sstats.pop("stale_better_overrides")) + list(sstats.pop("stale_inverted"))
    for k, v in sstats.items():
        print(f"  {k}: {v}")
    if stale and not args.allow_stale_constants:
        print("\nERROR: curated entries in constants/known_stats.py match no stat:")
        for s in stale:
            print(f"  {s!r}")
        print("Fix or remove them — a table that matches nothing reads as if it worked.")
        return 1

    print("building items.ndjson ...")
    item_records, istats = emit_items.build(trade_items, bases, classes, armour, tags)
    for k, v in istats.items():
        print(f"  {k}: {v}")

    class_records = emit_items.build_classes(classes, TRADE_CATEGORY_BY_CLASS_ID)
    mapped = sum(1 for c in class_records if c["tradeCategory"])
    print(f"  item classes: {len(class_records)} ({mapped} mapped to a trade category)")

    # ndjson + indices
    stats_path = out / f"{LANG}-stats.ndjson"
    stat_lines = _write_ndjson(stats_path, stat_records)
    matcher_pairs: list[tuple[str, int]] = []
    ref_pairs: list[tuple[str, int]] = []
    for rec, (_, off) in zip(stat_records, stat_lines):
        ref_pairs.append((rec["ref"], off))
        for m in rec["matchers"]:
            matcher_pairs.append((m["string"], off))
    _index_file(out / f"{LANG}-stats-matcher.index.bin", matcher_pairs, "stats-matcher")
    _index_file(out / f"{LANG}-stats-ref.index.bin", ref_pairs, "stats-ref")

    items_path = out / f"{LANG}-items.ndjson"
    item_lines = _write_ndjson(items_path, item_records)
    name_pairs = [(f"{r['namespace']}::{r['name']}", off)
                  for r, (_, off) in zip(item_records, item_lines)]
    ref_item_pairs = [(f"{r['namespace']}::{r['refName']}", off)
                      for r, (_, off) in zip(item_records, item_lines)]
    _index_file(out / f"{LANG}-items-name.index.bin", name_pairs, "items-name")
    _index_file(out / f"{LANG}-items-ref.index.bin", ref_item_pairs, "items-ref")

    _write_ndjson(out / "item-classes.ndjson", class_records)

    _write_vectors(out, stat_records)

    data_version = args.data_version or _dt.datetime.now(_dt.UTC).strftime("%Y%m%d") + ".0"
    generated_at = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    m = emit_manifest.build(out, data_version, game_patch, generated_at,
                            {"trade_stats_last_modified": stats_lm,
                             "trade_items_last_modified": items_lm},
                            tag=args.tag)
    emit_manifest.write(out, m)

    total = sum(f["size"] for f in m["files"])
    print(f"\nwrote {len(m['files'])} files, {total/1e6:.2f} MB total, to {out}")
    return 0


def _write_vectors(out: Path, stat_records: list[dict]) -> None:
    """Conformance vectors so the C++ normalizer can be proven to agree with this one.

    Without these the two implementations drift silently, and silently-wrong stat matching
    is the worst failure mode this project has.
    """
    samples = [
        "+42 to maximum Life", "23% increased Physical Damage",
        "Adds 5 to 12 Physical Damage", "Adds 5(4-6) to 12(10-14) Physical Damage",
        "+25(20-30)% to Cold Resistance", "1 Added Passive Skill is a Jewel Socket",
        "No Physical Damage", "Grants 1-30 Life per Enemy Hit",
        "-20% to Fire Resistance", "0.5% of Physical Attack Damage Leeched as Life",
        "+1 to Level of all Fire Skill Gems", "12% reduced Attack Speed",
        "Adds 1 to 2 Lightning Damage to Attacks", "100% increased Rarity of Items found",
        "+3.5% to Critical Strike Chance", "Regenerate 1.4 Life per second",
    ]
    # Plus real matcher strings with their numbers put back, so the vectors cover shapes
    # that only occur in live data.
    for rec in stat_records[:400]:
        s = rec["matchers"][0]["string"]
        if "#" in s:
            samples.append(s.replace("#", "7", 1))

    with (out / "stat-normalization-vectors.ndjson").open("w", encoding="utf-8") as f:
        for line in dict.fromkeys(samples):
            f.write(json.dumps({"line": line,
                                "generic": normalize.placeholder_form(line),
                                "candidates": normalize.candidates(line)},
                               ensure_ascii=False, sort_keys=True) + "\n")

    keys = ["", "a", "abc", "+# to maximum Life", "#% increased Physical Damage",
            "ITEM::Two-Stone Ring", "UNIQUE::Abberath's Hooves", "No Physical Damage"]
    (out / "fnv1a-vectors.json").write_text(json.dumps(
        {"algorithm": "fnv1a32", "vectors": [{"key": k, "hash": emit_index.fnv1a32(k)}
                                             for k in keys]}, indent=2) + "\n")


def cmd_verify(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    m = json.loads((out / "manifest.json").read_text())
    bad = 0
    for f in m["files"]:
        p = out / f["name"]
        if not p.exists():
            print(f"MISSING {f['name']}")
            bad += 1
            continue
        if p.stat().st_size != f["size"]:
            print(f"SIZE MISMATCH {f['name']}")
            bad += 1
        if emit_manifest.sha256_file(p) != f["sha256"]:
            print(f"SHA MISMATCH {f['name']}")
            bad += 1

    # Every index offset must land on the first byte of a line, or the client reads garbage.
    import struct
    for ndjson_name, idx_names in (
        (f"{LANG}-stats.ndjson", [f"{LANG}-stats-matcher.index.bin", f"{LANG}-stats-ref.index.bin"]),
        (f"{LANG}-items.ndjson", [f"{LANG}-items-name.index.bin", f"{LANG}-items-ref.index.bin"]),
    ):
        blob = (out / ndjson_name).read_bytes()
        starts = {0}
        for i, b in enumerate(blob):
            if b == 0x0A and i + 1 < len(blob):
                starts.add(i + 1)
        for idx_name in idx_names:
            raw = (out / idx_name).read_bytes()
            if len(raw) % 8:
                print(f"BAD INDEX SIZE {idx_name}")
                bad += 1
                continue
            prev_hash = -1
            for i in range(0, len(raw), 8):
                h, off = struct.unpack_from("<II", raw, i)
                if h < prev_hash:
                    print(f"INDEX NOT SORTED {idx_name} at row {i//8}")
                    bad += 1
                    break
                prev_hash = h
                if off not in starts:
                    print(f"INDEX OFFSET NOT A LINE START {idx_name} row {i//8} off {off}")
                    bad += 1
                    break

    print("verify: OK" if not bad else f"verify: {bad} problem(s)")
    return 1 if bad else 0


def cmd_vectors(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    _write_vectors(out, [])
    print(f"wrote vectors to {out}")
    return 0



def _keys(path: Path, fn) -> set[str]:
    if not path.exists():
        return set()
    return {fn(json.loads(line)) for line in path.open(encoding="utf-8") if line.strip()}


def cmd_notes(args: argparse.Namespace) -> int:
    """Release notes as a diff against the previous bundle.

    This is the review surface: a league launch should show dozens of additions, a routine
    rebuild zero. A silent republish with no visible reason is the thing to catch.
    """
    old, new = Path(args.old), Path(args.new)
    out = []

    for label, fname, key in (
        ("base types / uniques", f"{LANG}-items.ndjson",
         lambda r: f"{r['namespace']}::{r['name']}"),
        ("stat wordings", f"{LANG}-stats.ndjson", lambda r: r["ref"]),
        ("item classes", "item-classes.ndjson", lambda r: r["itemClass"]),
    ):
        before, after = _keys(old / fname, key), _keys(new / fname, key)
        if not before:
            out.append(f"- **{label}**: {len(after)} (no previous bundle to compare)")
            continue
        added, removed = sorted(after - before), sorted(before - after)
        if not added and not removed:
            out.append(f"- **{label}**: unchanged ({len(after)})")
            continue
        out.append(f"- **{label}**: {len(after)} total, +{len(added)} / -{len(removed)}")
        for name in added[:25]:
            out.append(f"  - added `{name}`")
        if len(added) > 25:
            out.append(f"  - ... and {len(added) - 25} more additions")
        for name in removed[:25]:
            out.append(f"  - removed `{name}`")
        if len(removed) > 25:
            out.append(f"  - ... and {len(removed) - 25} more removals")

    m = json.loads((new / "manifest.json").read_text())
    header = [f"Game patch `{m['game_patch']}`, schema v{m['schema_version']}.", ""]
    text = "\n".join(header + out) + "\n"
    if args.output:
        Path(args.output).write_text(text)
    print(text)
    return 0

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ppcdata")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("--out", default="out")
    b.add_argument("--workdir", default=".work")
    b.add_argument("--patch", default=None)
    b.add_argument("--data-version", default=None)
    b.add_argument("--tag", default=None)
    b.add_argument("--allow-stale-constants", action="store_true",
                   help="report, don't fail, when a curated stat entry matches nothing")
    b.add_argument("--skip-extract", action="store_true",
                   help="reuse an existing extraction in --workdir")
    b.set_defaults(fn=cmd_build)

    v = sub.add_parser("verify")
    v.add_argument("--out", default="out")
    v.set_defaults(fn=cmd_verify)

    n = sub.add_parser("notes")
    n.add_argument("--old", default="prev")
    n.add_argument("--new", default="out")
    n.add_argument("--output", default=None)
    n.set_defaults(fn=cmd_notes)

    x = sub.add_parser("vectors")
    x.add_argument("--out", default="out")
    x.set_defaults(fn=cmd_vectors)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
