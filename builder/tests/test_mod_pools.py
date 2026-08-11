from ppcdata.emit import mod_pools
from ppcdata.statdesc import Description, Variant

MAP = 5
CHART = 39


def _desc(stat_ids, text):
    return Description(stat_ids=list(stat_ids),
                       variants=[Variant(ranges=["#"] * len(stat_ids), text=text,
                                         placeholders=list(range(text.count("#"))))])


def _rec(ref, ids, dp=0):
    r = {"ref": ref, "matchers": [{"string": ref}], "better": 1, "trade": {"ids": ids}}
    if dp:
        r["dp"] = dp
    return r


def _mod(index, ident, name, domain, gen, stats):
    """``stats`` is ``[(stat row, min, max)]``, in the order the mod lists them."""
    m = {"_index": index, "Id": ident, "Name": name, "Domain": domain, "GenerationType": gen}
    for i, (row, lo, hi) in enumerate(stats, start=1):
        m[f"StatsKey{i}"] = row
        m[f"Stat{i}Min"] = lo
        m[f"Stat{i}Max"] = hi
    return m


STATS = [
    {"_index": 1, "Id": "map_monster_life_+%"},
    {"_index": 2, "Id": "map_monster_movement_speed_+%"},
    {"_index": 3, "Id": "map_monster_attack_speed_+%"},
    {"_index": 4, "Id": "map_item_quantity_+%"},
    # No description at all: a hidden stat, the way a cosmetic footprint is.
    {"_index": 5, "Id": "map_hidden_bookkeeping"},
    {"_index": 6, "Id": "map_thorns"},
    {"_index": 7, "Id": "map_dev_only"},
]
DESCS = [
    _desc(["map_monster_life_+%"], "#% more Monster Life"),
    _desc(["map_monster_movement_speed_+%"], "#% increased Monster Movement Speed"),
    _desc(["map_monster_attack_speed_+%"], "#% increased Monster Attack Speed"),
    _desc(["map_item_quantity_+%"], "#% Item Quantity"),
    # The client's markup, which stands between this wording and its stat record.
    _desc(["map_thorns"], "Monsters have [PhysicalThorns|Physical Thorns] reflecting # Damage"),
    _desc(["map_dev_only"], "[DNT] Area contains a Test Chest"),
]
RECORDS = [
    _rec("#% more Monster Life", {"explicit": ["explicit.stat_life"]}),
    _rec("#% increased Monster Movement Speed", {"explicit": ["explicit.stat_ms"]}),
    _rec("#% increased Monster Attack Speed", {"explicit": ["explicit.stat_as"]}),
    _rec("#% Item Quantity", {"explicit": ["explicit.stat_iiq"],
                              "implicit": ["implicit.stat_iiq"]}),
    _rec("Monsters have Physical Thorns reflecting # Damage",
         {"explicit": ["explicit.stat_thorns"]}),
]

# Three tiers of one prefix, its side-area twin, a two-wording suffix, a corruption implicit,
# a mod every stat of which is hidden, and a chart affix.
MODS = [
    _mod(0, "MapMonsterLife", "Fecund", MAP, 1, [(1, 20, 29)]),
    _mod(1, "MapMonsterLife2", "Fecund", MAP, 1, [(1, 30, 39)]),
    _mod(2, "MapMonsterLife3", "Emaciated", MAP, 1, [(1, 40, 49)]),
    _mod(3, "CorruptedSideAreaMonsterLife", "Fecund", MAP, 1, [(1, 20, 29)]),
    _mod(4, "MapMonsterFast", "of Speed", MAP, 2, [(2, 10, 20), (3, 15, 25)]),
    _mod(5, "MapCorruptionItemQuantity", "", MAP, 5, [(4, 5, 10)]),
    _mod(6, "MapBookkeeping", "of Nothing", MAP, 1, [(5, 1, 1)]),
    _mod(7, "MapDeepwaterChartMonsterLife", "Briny", CHART, 1, [(1, 50, 60)]),
    # Not in an emitted domain at all: an ordinary item affix.
    _mod(8, "IncreasedLife1", "of the Whale", 1, 1, [(1, 1, 2)]),
]


def _build(mods=None, stats=None, descs=None, records=None):
    return mod_pools.build(mods or MODS, stats or STATS, descs or DESCS, records or RECORDS)


def _by_name(records):
    return {r.get("name", r["mods"][0]): r for r in records}


def test_tiers_of_one_affix_collapse_to_one_entry_spanning_them():
    recs, stats = _build()
    entry = _by_name(recs)["Fecund"]
    assert entry["domain"] == MAP and entry["gen"] == 1
    # Every row behind the wording, the side-area twin included: `mods` is provenance for a
    # debug log that has to explain itself, in the table's own order, and a row that shares a
    # live wording is part of where that wording came from.
    assert entry["tiers"] == 4
    assert entry["mods"] == ["MapMonsterLife", "MapMonsterLife2", "MapMonsterLife3",
                             "CorruptedSideAreaMonsterLife"]
    # The lowest tier's floor to the highest tier's ceiling — what a regex written against a
    # printed line is tested against.
    assert entry["stats"] == [{"ref": "#% more Monster Life", "trade": "explicit.stat_life",
                               "min": 20, "max": 49}]
    assert stats["entries"] == 4
    assert stats["mod_rows"] == 7


def test_the_name_a_wording_set_disagrees_on_is_reported_not_hidden():
    # "Emaciated" is the third tier's name here; the most common one wins and the count says a
    # set disagreed, because the name is decoration and the wording underneath it is not.
    _, stats = _build()
    assert stats["sets_whose_rows_disagree_on_name"] == 1


def test_a_modifier_wording_several_stats_carries_one_entry_per_wording():
    entry = _by_name(_build()[0])["of Speed"]
    assert entry["gen"] == 2
    assert [s["ref"] for s in entry["stats"]] == ["#% increased Monster Movement Speed",
                                                  "#% increased Monster Attack Speed"]
    assert entry["stats"][1] == {"ref": "#% increased Monster Attack Speed",
                                 "trade": "explicit.stat_as", "min": 15, "max": 25}


def test_a_corruption_implicit_is_searched_in_the_implicit_namespace():
    entry = _by_name(_build()[0])["MapCorruptionItemQuantity"]
    assert entry["gen"] == 5
    assert entry["stats"][0]["trade"] == "implicit.stat_iiq"


def test_a_side_area_twin_leaves_the_wording_alone_but_never_stands_on_its_own():
    # The Fecund entry keeps its three live rows and drops the side-area one only because that
    # row's wording is shared. A set that is *all* side-area rows is the one that goes.
    recs, stats = _build(MODS + [_mod(9, "CorruptedSideAreaOnly", "of Nowhere", MAP, 1,
                                      [(2, 1, 2)])])
    assert "of Nowhere" not in _by_name(recs)
    assert stats["never_printed_dropped"] == 1


def test_a_modifier_with_no_wording_at_all_is_not_an_entry():
    assert "of Nothing" not in _by_name(_build()[0])


def test_a_domain_outside_the_pool_is_not_emitted():
    assert "of the Whale" not in _by_name(_build()[0])


def test_a_chart_affix_keeps_its_own_domain():
    # Charts share wordings with maps and are a pool of their own, so the entries stay apart
    # even where the wording is the same string.
    recs = _build()[0]
    chart = [r for r in recs if r["domain"] == CHART]
    assert len(chart) == 1 and chart[0]["mods"] == ["MapDeepwaterChartMonsterLife"]
    assert chart[0]["stats"][0]["ref"] == _by_name(recs)["Fecund"]["stats"][0]["ref"]


def test_the_clients_markup_is_rendered_so_the_wording_reaches_its_trade_id():
    recs, _ = _build(MODS + [_mod(9, "MapThorns", "Reflective", MAP, 1, [(6, 100, 200)])])
    entry = _by_name(recs)["Reflective"]
    assert entry["stats"] == [{"ref": "Monsters have Physical Thorns reflecting # Damage",
                               "trade": "explicit.stat_thorns", "min": 100, "max": 200}]


def test_a_developer_only_wording_is_left_out():
    recs, stats = _build(MODS + [_mod(9, "MapDevChest", "of Testing", MAP, 1, [(7, 1, 1)])])
    assert "of Testing" not in _by_name(recs)
    assert stats["never_printed_dropped"] == 1


def test_a_wording_trade_does_not_index_is_still_an_entry():
    # The pool is rated, not searched: a modifier with no hash is one a player can still hold
    # and still have an opinion about.
    descs = DESCS + [_desc(["map_no_trade"], "Area is inhabited by Test Monsters")]
    stats_rows = STATS + [{"_index": 8, "Id": "map_no_trade"}]
    mods = MODS + [_mod(9, "MapTestMonsters", "Testing", MAP, 1, [(8, 1, 1)])]
    recs, counts = mod_pools.build(mods, stats_rows, descs, RECORDS)
    entry = _by_name(recs)["Testing"]
    assert entry["stats"] == [{"ref": "Area is inhabited by Test Monsters"}]
    assert counts["wordings_without_trade_id"] == 1


def test_ranges_are_emitted_in_displayed_units():
    records = RECORDS + [_rec("#% increased Monster Critical Strike Chance",
                              {"explicit": ["explicit.stat_crit"]}, dp=2)]
    descs = DESCS + [_desc(["map_monster_crit"],
                           "#% increased Monster Critical Strike Chance")]
    stats_rows = STATS + [{"_index": 8, "Id": "map_monster_crit"}]
    mods = MODS + [_mod(9, "MapMonsterCrit", "Deadly", MAP, 1, [(8, 350, 500)])]
    recs, _ = mod_pools.build(mods, stats_rows, descs, records)
    # Mods.dat stores hundredths; leaving that to the client is a silent factor of 100.
    assert _by_name(recs)["Deadly"]["stats"][0] == {
        "ref": "#% increased Monster Critical Strike Chance", "trade": "explicit.stat_crit",
        "min": 3.5, "max": 5}
