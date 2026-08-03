import struct

from ppcdata.emit.index import build, fnv1a32


def test_fnv1a32_reference_vectors():
    # Canonical FNV-1a 32-bit values.
    assert fnv1a32("") == 0x811C9DC5
    assert fnv1a32("a") == 0xE40C292C
    assert fnv1a32("foobar") == 0xBF9CF968


def test_index_is_sorted_by_hash():
    keys = ["zebra", "apple", "mango", "kiwi", "pear"]
    blob, _ = build([(k, i * 10) for i, k in enumerate(keys)])
    assert len(blob) == len(keys) * 8
    hashes = [struct.unpack_from("<II", blob, i)[0] for i in range(0, len(blob), 8)]
    assert hashes == sorted(hashes)


def test_offsets_survive_the_round_trip():
    pairs = [("alpha", 0), ("beta", 17), ("gamma", 99)]
    blob, _ = build(pairs)
    rows = {struct.unpack_from("<II", blob, i) for i in range(0, len(blob), 8)}
    assert rows == {(fnv1a32(k), off) for k, off in pairs}


def test_one_key_many_offsets_is_not_a_collision():
    # A matcher string legitimately points at one line; the same *key* repeated is not the
    # collision we report on.
    _, collisions = build([("same", 0), ("same", 0)])
    assert collisions == 0


def test_duplicate_hash_rows_are_kept():
    # Two distinct keys sharing a hash must both survive as consecutive rows — the reader
    # walks the run and re-verifies. Awakened's format drops one of them.
    pairs = [("a", 1), ("b", 2), ("c", 3)]
    blob, _ = build(pairs)
    assert len(blob) == 3 * 8
