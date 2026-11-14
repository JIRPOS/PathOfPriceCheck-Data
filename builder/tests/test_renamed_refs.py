import pytest

from ppcdata.constants.renamed_refs import NOT_RENAMED, RENAMED
from ppcdata.emit import renamed_refs as emit


def _pool(*records):
    return [{"mods": list(mods), "stats": [{"ref": r} for r in refs]} for mods, refs in records]


def test_a_reworded_line_is_proposed_and_a_line_added_everywhere_is_not():
    old = _pool((["A1", "A2"], ["# Scarabs"]), (["B1"], ["# Totems"]))
    new = _pool((["A1", "A2"], ["# Threads", "# Atlas Drops"]), (["B1"], ["# Totems", "# Atlas Drops"]))
    assert emit.detect(old, new) == {"# Scarabs": "# Threads"}


def test_two_new_lines_where_one_went_are_not_guessed_between():
    old = _pool((["A1"], ["# Scarabs"]))
    new = _pool((["A1"], ["# Threads", "# Embers"]))
    assert emit.detect(old, new) == {}


def test_chains_collapse_and_contradicted_entries_are_left_out():
    doc, dropped = emit.build({"a": "b", "b": "c", "x": "y", "live": "c"}, {"c", "live"})
    assert doc == {"renamed": {"a": "c", "b": "c"}}
    assert len(dropped) == 2


def test_a_loop_is_refused():
    with pytest.raises(ValueError):
        emit.build({"a": "b", "b": "a"}, {"a", "b"})


def test_the_tables_do_not_overlap():
    assert not (RENAMED.keys() & NOT_RENAMED.keys())
