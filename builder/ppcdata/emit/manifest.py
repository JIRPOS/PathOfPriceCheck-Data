"""manifest.json — what the client fetches first to decide whether to download anything."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = 1

RELEASE_URL = ("https://github.com/JIRPOS/PathOfPriceCheck-Data/releases/download/"
               "{tag}/{name}")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(outdir: Path, data_version: str, game_patch: str, generated_at: str,
          source: dict, tag: str | None = None) -> dict:
    tag = tag or f"data-{data_version}"
    files = []
    for p in sorted(outdir.iterdir()):
        if not p.is_file() or p.name == "manifest.json":
            continue
        size = p.stat().st_size
        files.append({
            "name": p.name,
            "sha256": sha256_file(p),
            "size": size,
            # Per-file, so gzip can be introduced later as a capability the client either
            # understands or refuses — not as a format break.
            "encoding": "none",
            "compressed_size": size,
            "url": RELEASE_URL.format(tag=tag, name=p.name),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "data_version": data_version,
        "generated_at": generated_at,
        "game_patch": game_patch,
        "languages": ["en"],
        "source": source,
        "files": files,
    }


def write(outdir: Path, manifest: dict) -> None:
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def outputs_match(a: dict, b: dict) -> bool:
    """Compare the *outputs* of two builds, ignoring timestamps and version strings.

    Inputs churn without outputs changing — GGG re-serves identical bodies — so comparing
    file hashes is the honest gate for "is a new release warranted".
    """
    def sig(m: dict) -> dict:
        return {f["name"]: f["sha256"] for f in m.get("files", [])}
    return sig(a) == sig(b)
