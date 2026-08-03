"""fnv1a32 lookup indices over an ndjson file.

Layout: a flat little-endian array of ``[u32 hash, u32 byte_offset]`` rows sorted ascending
by hash. The client binary-searches the hash column and JSON-parses the line at the offset.

One deliberate difference from Awakened's format: duplicate hash rows are allowed. Theirs
stores one offset per hash and silently loses colliding keys; we control both ends, so a
collision becomes a short run the reader walks, verifying each candidate. Zero extra bytes
in the common case.
"""

from __future__ import annotations

import struct

FNV1A_OFFSET = 0x811C9DC5
FNV1A_PRIME = 0x01000193
MASK32 = 0xFFFFFFFF


def fnv1a32(s: str) -> int:
    h = FNV1A_OFFSET
    for b in s.encode("utf-8"):
        h = ((h ^ b) * FNV1A_PRIME) & MASK32
    return h


def build(pairs: list[tuple[str, int]]) -> tuple[bytes, int]:
    """Serialise ``(key, byte_offset)`` pairs. Returns ``(blob, collision_count)``.

    A collision here means two *different* keys sharing a hash — worth reporting, since a
    spike signals the key space has changed shape.
    """
    rows = sorted(((fnv1a32(k), off, k) for k, off in pairs), key=lambda r: (r[0], r[1]))
    collisions = 0
    for i in range(1, len(rows)):
        if rows[i][0] == rows[i - 1][0] and rows[i][2] != rows[i - 1][2]:
            collisions += 1
    blob = b"".join(struct.pack("<II", h, off) for h, off, _ in rows)
    return blob, collisions
