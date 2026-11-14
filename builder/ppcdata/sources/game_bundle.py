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

DESCRIPTIONS_DIR = "Metadata/StatDescriptions/"

# The raw asset carrying every stat wording. PoE 1 keeps it under Metadata/; the
# data/StatDescriptions/ path is PoE 2 and does not exist here.
STAT_DESCRIPTIONS = "stat_descriptions"

# The main file does not cover everything: map, chest, heist and sanctum mods are worded in
# their own files, and without them those wordings fall back to the trade text and lose
# their negate and fixed-value forms. Best-effort — GGG adds and removes these between
# leagues, so a missing one is dropped rather than failing the build.
OPTIONAL_DESCRIPTIONS = [
    "map_stat_descriptions",
    "chest_stat_descriptions",
    "heist_equipment_stat_descriptions",
    "sanctum_relic_stat_descriptions",
    "necropolis_stat_descriptions",
    "crucible_stat_descriptions",
    "mercenary_stat_descriptions",
    "ultimatum_stat_descriptions",
    "delve_stat_descriptions",
    "gem_stat_descriptions",
]

# 3.30 renamed every description file from .txt to .csd, PoE 2's extension, with the text
# grammar unchanged. Earlier patches have only .txt. One extension serves the whole set: were
# the main file found under .csd while the optional ones were still asked for as .txt, every
# optional file would be dropped as "not in this patch" and the build would pass without them.
DESCRIPTION_EXTENSIONS = (".csd", ".txt")


def _description_files(ext: str) -> tuple[str, list[str]]:
    return (DESCRIPTIONS_DIR + STAT_DESCRIPTIONS + ext,
            [DESCRIPTIONS_DIR + name + ext for name in OPTIONAL_DESCRIPTIONS])


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
    # The two tables a stat description can render a value *out of* rather than print. A mod
    # rolling "+3 to Level of all <one of 287 gems>" stores the gem as a row number here, and
    # without these the wording stays "+# to Level of all # Gems" — which trade indexes under
    # no id at all, because it indexes one id per gem. The name column differs between the two
    # tables; that is GGG's shape, not a typo here.
    {"name": "IndexableSkillGems", "columns": ["Name1"]},
    {"name": "IndexableSupportGems", "columns": ["Name"]},
    # 3.30: the minion type The Dark Monarch doubles, by the same one-based row number.
    {"name": "MinionDoublingStatTypes", "columns": ["Name"]},
]

#: statdesc's table name -> (dat table, its display-name column).
INDEXABLE_TABLES = {"skill": ("IndexableSkillGems", "Name1"),
                    "support": ("IndexableSupportGems", "Name"),
                    "minion_doubling": ("MinionDoublingStatTypes", "Name")}


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

    # The extractor adds to files/ rather than replacing it, so a workdir reused across a
    # patch would mix both extensions' files into one build.
    shutil.rmtree(workdir / "files", ignore_errors=True)

    for ext in DESCRIPTION_EXTENSIONS:
        main, optional = _description_files(ext)
        wanted = [main] + optional
        for _ in range(len(optional) + 1):
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
            if m and m.group(1) == main:
                print(f"  note: no {main} in this patch; trying the next extension")
                break
            if m and m.group(1) in optional and m.group(1) in wanted:
                print(f"  note: {m.group(1)} is not in this patch; skipping")
                wanted.remove(m.group(1))
                continue
            raise RuntimeError(f"pathofexile-dat failed ({rc}):\n{out[-2000:]}")
        else:
            raise RuntimeError(
                "pathofexile-dat kept failing after dropping every optional file")

    raise RuntimeError("no stat_descriptions file under any known extension: "
                       + ", ".join(DESCRIPTION_EXTENSIONS))


def table(workdir: Path, name: str) -> list[dict]:
    p = workdir / "tables" / "English" / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(f"table not extracted: {p}")
    return json.loads(p.read_text())


def indexable_names(workdir: Path) -> dict[str, list[str]]:
    """``{"skill": [...], "support": [...]}`` — display names by row, in row order.

    A stat's value is the row number **one-based**, so row 0 is value 1. That is not an
    assumption: the game prints the whole range of such a roll as its first and last name,
    and "(Fireball-Mana-Infused Staff)" is rows 0 and 286 of a 287-row table against a mod
    whose range is 1..287.
    """
    out: dict[str, list[str]] = {}
    for kind, (name, column) in INDEXABLE_TABLES.items():
        out[kind] = [r[column] for r in table(workdir, name)]
    return out


def stat_descriptions_path(workdir: Path) -> Path:
    """The main description file that landed, or the newest format's path if none did."""
    for ext in DESCRIPTION_EXTENSIONS:
        p = workdir / "files" / _description_files(ext)[0].replace("/", "@")
        if p.exists():
            return p
    return workdir / "files" / _description_files(DESCRIPTION_EXTENSIONS[0])[0].replace("/", "@")


def description_paths(workdir: Path) -> list[Path]:
    """Every stat-description file that landed, main one first."""
    main = stat_descriptions_path(workdir)
    if not main.exists():
        return []
    rest = sorted(p for p in main.parent.glob("*stat_descriptions" + main.suffix) if p != main)
    return [main] + rest
