"""Game data extraction via `pathofexile-dat`.

That tool downloads GGG's own .datc64 bundles straight from the patch CDN and decodes them
with poe-tool-dev/dat-schema. It depends on ooz-wasm, so Oodle decompression runs in
WebAssembly — no native blob, no game install, works on a stock CI runner with only Node.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

DAT_VERSION = "15.2.0"

# The raw asset carrying every stat wording. PoE 1 keeps it under Metadata/; the
# data/StatDescriptions/*.csd path is PoE 2 and does not exist here.
STAT_DESCRIPTIONS = "Metadata/StatDescriptions/stat_descriptions.txt"

# The main file does not cover everything: map, chest, heist and sanctum mods are worded in
# their own files, and without them those wordings fall back to the trade text and lose
# their negate and fixed-value forms. Best-effort — GGG adds and removes these between
# leagues, so a missing one is dropped rather than failing the build.
OPTIONAL_DESCRIPTIONS = [
    "Metadata/StatDescriptions/map_stat_descriptions.txt",
    "Metadata/StatDescriptions/chest_stat_descriptions.txt",
    "Metadata/StatDescriptions/heist_equipment_stat_descriptions.txt",
    "Metadata/StatDescriptions/sanctum_relic_stat_descriptions.txt",
    "Metadata/StatDescriptions/necropolis_stat_descriptions.txt",
    "Metadata/StatDescriptions/crucible_stat_descriptions.txt",
    "Metadata/StatDescriptions/mercenary_stat_descriptions.txt",
    "Metadata/StatDescriptions/ultimatum_stat_descriptions.txt",
    "Metadata/StatDescriptions/delve_stat_descriptions.txt",
    "Metadata/StatDescriptions/gem_stat_descriptions.txt",
]

_MISSING_PATH = re.compile(r"path:\s*'([^']+)'")

TABLES = [
    {"name": "ItemClasses", "columns": ["Id", "Name", "ItemClassCategory"]},
    {"name": "ItemClassCategories", "columns": ["Id", "Text"]},
    {"name": "BaseItemTypes", "columns": [
        "Id", "Name", "ItemClassesKey", "Width", "Height", "DropLevel",
        "TagsKeys", "Implicit_ModsKeys", "IsCorrupted", "InheritsFrom", "ModDomain"]},
    # A unique's artwork, which GGG's own CDN serves at the DDS path with a .png extension:
    # https://web.poecdn.com/image/Art/2DItems/Armours/Gloves/Hrimsorrow.png. A unique is not a
    # row in BaseItemTypes — it is a name, a base and a mod list assembled at drop time — so the
    # only join that reaches its art is the unique stash tab's layout, where `Words` holds the
    # display name the client prints and the clipboard repeats.
    {"name": "ItemVisualIdentity", "columns": ["DDSFile"]},
    {"name": "UniqueStashLayout", "columns": [
        "WordsKey", "ItemVisualIdentityKey", "IsAlternateArt"]},
    {"name": "Words", "columns": ["Text"]},
    {"name": "Tags", "columns": ["Id"]},
    {"name": "Stats", "columns": ["Id", "IsLocal", "IsWeaponLocal"]},
    # All eight stat slots, not the first six: a unique's mod that granted a seventh stat
    # would otherwise lose that filter silently, and 541 mods already reach the sixth.
    {"name": "Mods", "columns": [
        "Id", "Level", "Domain", "Name", "GenerationType",
        "StatsKey1", "StatsKey2", "StatsKey3", "StatsKey4",
        "StatsKey5", "StatsKey6", "StatsKey7", "StatsKey8",
        "Stat1Min", "Stat1Max", "Stat2Min", "Stat2Max", "Stat3Min", "Stat3Max",
        "Stat4Min", "Stat4Max", "Stat5Min", "Stat5Max", "Stat6Min", "Stat6Max",
        "Stat7Min", "Stat7Max", "Stat8Min", "Stat8Max"]},
    {"name": "ArmourTypes", "columns": [
        "BaseItemTypesKey", "ArmourMin", "ArmourMax", "EvasionMin", "EvasionMax",
        "EnergyShieldMin", "EnergyShieldMax", "WardMin", "WardMax"]},
    {"name": "WeaponTypes", "columns": [
        "BaseItemTypesKey", "DamageMin", "DamageMax", "Speed", "Critical", "RangeMax"]},
]


def write_config(workdir: Path, patch: str, files: list[str]) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "patch": patch,
        "translations": ["English"],
        "files": files,
        "tables": TABLES,
    }
    (workdir / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")


def _run(workdir: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["npx", "--yes", f"pathofexile-dat@{DAT_VERSION}"],
        cwd=workdir, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def extract(workdir: Path, patch: str) -> list[str]:
    """Run the extractor in ``workdir``. Returns the description files that landed.

    The tool aborts the whole run on the first path it cannot find, so a description file
    GGG has since removed would take the build down with it. Drop the offending path and
    retry instead — that keeps the optional files genuinely optional. The bundle cache in
    ``workdir/.cache`` makes each retry cheap.
    """
    if shutil.which("npx") is None:
        raise RuntimeError("npx not found; Node is required to extract game data")

    wanted = [STAT_DESCRIPTIONS] + OPTIONAL_DESCRIPTIONS
    for _ in range(len(OPTIONAL_DESCRIPTIONS) + 1):
        write_config(workdir, patch, wanted)
        rc, out = _run(workdir)

        # The tool exits 0 even when a table is missing a column, so scan its output. A
        # table changing shape is a real breakage and must fail loudly.
        if "doesn't have a column named" in out:
            bad = [ln for ln in out.splitlines() if "doesn't have a column" in ln]
            raise RuntimeError("dat-schema mismatch (a table changed shape):\n  "
                               + "\n  ".join(bad))
        if rc == 0:
            return wanted

        m = _MISSING_PATH.search(out) if "NoFileInfoError" in out else None
        if m and m.group(1) in OPTIONAL_DESCRIPTIONS and m.group(1) in wanted:
            print(f"  note: {m.group(1)} is not in this patch; skipping")
            wanted.remove(m.group(1))
            continue
        raise RuntimeError(f"pathofexile-dat failed ({rc}):\n{out[-2000:]}")

    raise RuntimeError("pathofexile-dat kept failing after dropping every optional file")


def table(workdir: Path, name: str) -> list[dict]:
    p = workdir / "tables" / "English" / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(f"table not extracted: {p}")
    return json.loads(p.read_text())


def stat_descriptions_path(workdir: Path) -> Path:
    return workdir / "files" / STAT_DESCRIPTIONS.replace("/", "@")


def description_paths(workdir: Path) -> list[Path]:
    """Every stat-description file that landed, main one first."""
    d = workdir / "files"
    if not d.is_dir():
        return []
    main = d / STAT_DESCRIPTIONS.replace("/", "@")
    rest = sorted(p for p in d.glob("*stat_descriptions.txt") if p != main)
    return ([main] if main.exists() else []) + rest
