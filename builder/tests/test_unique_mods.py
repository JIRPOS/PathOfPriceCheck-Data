from ppcdata.emit import unique_mods
from ppcdata.sources.wiki import unescape
from ppcdata.statdesc import Description, Variant


def _desc(stat_ids, text, negate=False):
    return Description(stat_ids=list(stat_ids),
                       variants=[_var(text, ["#"] * len(stat_ids), negate=negate)])


def _var(text, ranges, negate=False, indexable=None):
    """A variant with its placeholders numbered left to right, as the common case is."""
    return Variant(ranges=list(ranges), text=text, negate=negate,
                   placeholders=list(range(text.count("#"))), indexable=indexable)


def _rec(ref, ids, dp=0):
    r = {"ref": ref, "matchers": [{"string": ref}], "better": 1, "trade": {"ids": ids}}
    if dp:
        r["dp"] = dp
    return r


# Two stats behind one wording ("Adds # to # Fire Damage"), a hundredths stat, a hidden stat
# with no description at all, and a wording trade does not index.
STATS = [
    {"_index": 1, "Id": "fire_damage_+%"},
    {"_index": 2, "Id": "min_added_fire_damage"},
    {"_index": 3, "Id": "max_added_fire_damage"},
    {"_index": 4, "Id": "critical_strike_chance_+%"},
    {"_index": 5, "Id": "goat_hoof_footprints"},
    {"_index": 6, "Id": "base_maximum_life"},
]
DESCS = [
    _desc(["fire_damage_+%"], "#% increased Fire Damage"),
    _desc(["min_added_fire_damage", "max_added_fire_damage"], "Adds # to # Fire Damage"),
    _desc(["critical_strike_chance_+%"], "+#% to Critical Strike Chance"),
    _desc(["base_maximum_life"], "# to maximum Life"),
]
RECORDS = [
    _rec("#% increased Fire Damage", {"explicit": ["explicit.stat_fire"],
                                     "implicit": ["implicit.stat_fire"]}),
    _rec("Adds # to # Fire Damage", {"explicit": ["explicit.stat_adds_fire"]}),
    _rec("+#% to Critical Strike Chance", {"explicit": ["explicit.stat_crit"]}, dp=2),
]
MODS = [
    {"_index": 0, "Id": "FireDamageUnique__1", "StatsKey1": 1, "Stat1Min": 20, "Stat1Max": 30},
    {"_index": 1, "Id": "AddsFireUnique__1", "StatsKey1": 2, "Stat1Min": 5, "Stat1Max": 9,
     "StatsKey2": 3, "Stat2Min": 12, "Stat2Max": 18},
    {"_index": 2, "Id": "CritUnique__1", "StatsKey1": 4, "Stat1Min": 350, "Stat1Max": 500},
    {"_index": 3, "Id": "FootprintsUnique__1", "StatsKey1": 5, "Stat1Min": 1, "Stat1Max": 1},
    {"_index": 4, "Id": "LifeUnique__1", "StatsKey1": 6, "Stat1Min": 40, "Stat1Max": 60},
]


def _row(name, mod, base="Ruby Ring", rnd=0, impl=0, hint=None):
    return {"name": name, "base": base, "mod": mod, "rnd": rnd, "impl": impl, "hint": hint}


def _build(rows, known=("Test Ring",), descs=None, records=None, mods=None, stats=None,
           indexables=None):
    return unique_mods.build(rows, mods or MODS, stats or STATS, descs or DESCS,
                             records or RECORDS, set(known), indexables)


def test_fixed_mod_carries_its_trade_id_and_range():
    recs, _ = _build([_row("Test Ring", "FireDamageUnique__1")])
    assert len(recs) == 1
    assert recs[0]["base"] == "Ruby Ring"
    assert recs[0]["fixed"] == [{"mod": "FireDamageUnique__1", "filters": [
        {"ref": "#% increased Fire Damage", "tradeId": "explicit.stat_fire",
         "range": [[20, 30]]}]}]


def test_implicit_picks_the_implicit_namespace():
    recs, _ = _build([_row("Test Ring", "FireDamageUnique__1", impl=1)])
    entry = recs[0]["fixed"][0]
    assert entry["implicit"] is True
    assert entry["filters"][0]["tradeId"] == "implicit.stat_fire"


def test_one_wording_covering_two_stats_is_one_filter():
    # "Adds # to # Fire Damage" is two client stats and a single trade filter; emitting two
    # would search the minimum and the maximum as separate mods.
    recs, _ = _build([_row("Test Ring", "AddsFireUnique__1")])
    filters = recs[0]["fixed"][0]["filters"]
    assert len(filters) == 1
    assert filters[0]["tradeId"] == "explicit.stat_adds_fire"
    assert filters[0]["range"] == [[5, 9], [12, 18]]


def test_ranges_are_scaled_out_of_the_client_units():
    # Mods.dat stores hundredths for this stat; 350 is 3.5% on the item.
    recs, _ = _build([_row("Test Ring", "CritUnique__1")])
    assert recs[0]["fixed"][0]["filters"][0]["range"] == [[3.5, 5]]


def test_a_mod_with_only_hidden_stats_is_dropped():
    recs, stats = _build([_row("Test Ring", "FootprintsUnique__1"),
                          _row("Test Ring", "FireDamageUnique__1")])
    assert [e["mod"] for e in recs[0]["fixed"]] == ["FireDamageUnique__1"]
    assert stats["mods_with_no_searchable_stat"] == 1
    assert stats["stats_without_description"] == 1


def test_a_wording_trade_does_not_index_keeps_its_text_but_gets_no_id():
    # Not searchable, but the app still has to be able to show the mod.
    recs, stats = _build([_row("Test Ring", "LifeUnique__1")])
    f = recs[0]["fixed"][0]["filters"][0]
    assert f == {"ref": "# to maximum Life", "range": [[40, 60]]}
    assert stats["wordings_without_stat_record"] == 1


def test_random_mods_group_into_a_pool_with_its_count():
    rows = [_row("Test Ring", "FireDamageUnique__1", rnd=1,
                 hint="<Two or Three random aura modifiers>"),
            _row("Test Ring", "CritUnique__1", rnd=1,
                 hint="<Two or Three random aura modifiers>"),
            _row("Test Ring", "AddsFireUnique__1")]
    recs, stats = _build(rows)
    assert [e["mod"] for e in recs[0]["fixed"]] == ["AddsFireUnique__1"]
    pool = recs[0]["pools"][0]
    assert pool["count"] == [2, 3]
    assert pool["hint"] == "Two or Three random aura modifiers"
    assert [e["mod"] for e in pool["mods"]] == ["CritUnique__1", "FireDamageUnique__1"]
    assert stats["with_a_random_pool"] == 1


def test_a_pool_the_wiki_does_not_enumerate_is_carried_as_prose():
    rows = [_row("Test Ring", None, hint="<One to three random Synthesis implicit modifiers>"),
            _row("Test Ring", "FireDamageUnique__1")]
    recs, _ = _build(rows)
    assert recs[0]["unlisted"] == ["One to three random Synthesis implicit modifiers"]


def test_a_stale_wiki_mod_id_is_reported_not_guessed():
    recs, stats = _build([_row("Test Ring", "NoSuchMod__1"),
                          _row("Test Ring", "FireDamageUnique__1")])
    assert stats["wiki_mod_ids_not_in_client"] == 1
    assert len(recs[0]["fixed"]) == 1


def test_a_unique_trade_does_not_list_is_dropped():
    # Sanctum relics and tattoos are unique-rarity wiki pages that cannot be price checked.
    recs, stats = _build([_row("Cannibalistic Habits", "FireDamageUnique__1")])
    assert recs == []
    assert stats["not_in_trade_data"] == 1


def test_two_ids_behind_one_wording_are_not_guessed_between():
    ambiguous = RECORDS + [_rec("#% increased Fire Damage", {"explicit": ["explicit.other"]})]
    recs, stats = unique_mods.build([_row("Test Ring", "FireDamageUnique__1")],
                                    MODS, STATS, DESCS, ambiguous, {"Test Ring"})
    assert "tradeId" not in recs[0]["fixed"][0]["filters"][0]
    assert stats["ambiguous_wordings"] == 1


def test_duplicate_records_that_agree_on_the_id_are_not_ambiguous():
    # Trade lists 71 wordings twice, usually as one entry covering several namespaces and a
    # second covering only explicit. They agree on the id that matters.
    dupes = RECORDS + [_rec("#% increased Fire Damage", {"explicit": ["explicit.stat_fire"]})]
    recs, stats = unique_mods.build([_row("Test Ring", "FireDamageUnique__1")],
                                    MODS, STATS, DESCS, dupes, {"Test Ring"})
    assert recs[0]["fixed"][0]["filters"][0]["tradeId"] == "explicit.stat_fire"
    assert stats["ambiguous_wordings"] == 0


def test_hint_text_strips_the_wikis_markup():
    assert unique_mods.hint_text(unescape("&amp;lt;Random [[Keystone]]&amp;gt;")) \
        == "Random Keystone"
    # Unescaping is the source's job, so an entity left here survives visibly rather than
    # being half-cleaned into something that reads like prose.
    assert unique_mods.hint_text("&lt;Random Keystone&gt;") == "&lt;Random Keystone&gt;"
    assert unique_mods.hint_text(
        '<span class="tc -default">Requires Class</span>: '
        '<span class="tc -value">[[Character Class]]</span>') == "Requires Class: Character Class"
    assert unique_mods.hint_text(
        "<One Endurance Charge mod><br><One Frenzy Charge mod>") \
        == "One Endurance Charge mod / One Frenzy Charge mod"
    assert unique_mods.hint_text(
        "Allocates <random [[List of notable ascendancy passive skills|Ascendancy Notable]]>") \
        == "Allocates random Ascendancy Notable"


def test_parse_count():
    assert unique_mods.parse_count("Two or Three random aura modifiers") == [2, 3]
    assert unique_mods.parse_count("One to three random Synthesis implicit modifiers") == [1, 3]
    assert unique_mods.parse_count("Three Frenzy Charge mods") == [3, 3]
    assert unique_mods.parse_count("3 Random notable mods") == [3, 3]
    assert unique_mods.parse_count("2 random curse modifiers") == [2, 2]
    # No number stated: unknown, not one.
    assert unique_mods.parse_count("Random Herald of Ash modifier") is None
    # Several sub-pools in one hint. The leading number counts only its own segment and the
    # wiki gives no way to tell which pool mod belongs to which.
    assert unique_mods.parse_count("One Endurance Charge mod / One Frenzy Charge mod") is None


def test_cargo_escapes_twice():
    assert unescape("Abberath&amp;#039;s Hooves") == "Abberath's Hooves"
    assert unescape("Abberath&#039;s Hooves") == "Abberath's Hooves"
    assert unescape("&amp;lt;Two or Three random aura modifiers&amp;gt;") \
        == "<Two or Three random aura modifiers>"


# A modifier whose value is a name, in both shapes the game has: one wording per value, and a
# value that is a row number in a table of names.
OPTION_STATS = STATS + [
    {"_index": 7, "Id": "minion_type_doubled"},
    {"_index": 8, "Id": "random_gem_level"},
    {"_index": 9, "Id": "random_gem_index"},
]
OPTION_DESCS = DESCS + [
    Description(stat_ids=["minion_type_doubled"], variants=[
        _var("Maximum number of Zombies is Doubled", ["1"]),
        _var("Maximum number of Skeletons is Doubled", ["2"]),
        _var("Maximum number of Spectres is Doubled", ["3"]),
    ]),
    Description(stat_ids=["random_gem_level", "random_gem_index"], variants=[
        Variant(ranges=["1|#", "#"], text="+# to Level of all # Gems",
                placeholders=[0, 1], indexable=("skill", 1)),
        Variant(ranges=["#|-1", "#"], text="-# to Level of all # Gems",
                placeholders=[0, 1], indexable=("skill", 1)),
    ]),
]
OPTION_RECORDS = RECORDS + [
    _rec("Maximum number of Zombies is Doubled", {"explicit": ["explicit.stat_double|1"]}),
    _rec("Maximum number of Skeletons is Doubled", {"explicit": ["explicit.stat_double|2"]}),
    _rec("Maximum number of Spectres is Doubled", {"explicit": ["explicit.stat_double|3"]}),
    _rec("# to Level of all Fireball Gems", {"explicit": ["explicit.indexable_skill_1"]}),
    _rec("# to Level of all Ice Nova Gems", {"explicit": ["explicit.indexable_skill_2"]}),
]
OPTION_MODS = MODS + [
    {"_index": 5, "Id": "DoubleMinionUnique__1", "StatsKey1": 7, "Stat1Min": 1, "Stat1Max": 3},
    {"_index": 6, "Id": "RandomSkillUnique__1", "StatsKey1": 8, "Stat1Min": 3, "Stat1Max": 3,
     "StatsKey2": 9, "Stat2Min": 1, "Stat2Max": 2},
]
INDEXABLES = {"skill": ["Fireball", "Ice Nova"], "support": []}


def _build_options(rows):
    return _build(rows, descs=OPTION_DESCS, records=OPTION_RECORDS, mods=OPTION_MODS,
                  stats=OPTION_STATS, indexables=INDEXABLES)


def test_one_wording_per_value_becomes_a_pool_of_one():
    # The wiki calls this modifier fixed, and it is: every copy has it. What varies is which
    # of the three it rendered as, and a single filter would claim this copy rolled the first.
    recs, stats = _build_options([_row("Test Ring", "DoubleMinionUnique__1")])
    assert "fixed" not in recs[0]
    pool = recs[0]["pools"][0]
    assert pool["count"] == [1, 1]
    assert [f["tradeId"] for e in pool["mods"] for f in e["filters"]] == [
        "explicit.stat_double|1", "explicit.stat_double|2", "explicit.stat_double|3"]
    # The value is in the wording, so there is no range left to filter on.
    assert all(f["range"] == [] for e in pool["mods"] for f in e["filters"])
    assert stats["mods_rolling_a_named_option"] == 1
    assert stats["named_options"] == 3


def test_an_indexed_value_is_looked_up_and_the_other_range_survives():
    recs, _ = _build_options([_row("Test Ring", "RandomSkillUnique__1")])
    pool = recs[0]["pools"][0]
    assert [f["ref"] for e in pool["mods"] for f in e["filters"]] == [
        "# to Level of all Fireball Gems", "# to Level of all Ice Nova Gems"]
    assert [f["tradeId"] for e in pool["mods"] for f in e["filters"]] == [
        "explicit.indexable_skill_1", "explicit.indexable_skill_2"]
    # The level is still a number, and still the only one.
    assert all(f["range"] == [[3, 3]] for e in pool["mods"] for f in e["filters"])


def test_the_negative_wording_is_not_the_one_a_positive_roll_expands():
    # "+# to Level" and "-# to Level" differ only by their range specs, and a mod rolling 3..3
    # is the positive one. Picking by order instead would name every gem twice.
    recs, _ = _build_options([_row("Test Ring", "RandomSkillUnique__1")])
    refs = [f["ref"] for e in recs[0]["pools"][0]["mods"] for f in e["filters"]]
    assert len(refs) == 2 and not any(r.startswith("-") for r in refs)


def test_a_table_too_short_for_the_roll_expands_nothing():
    # Half a pool is worse than none: the modifier stays the single filter it was.
    mods = [m for m in OPTION_MODS if m["Id"] != "RandomSkillUnique__1"] + [
        {"_index": 6, "Id": "RandomSkillUnique__1", "StatsKey1": 8, "Stat1Min": 3, "Stat1Max": 3,
         "StatsKey2": 9, "Stat2Min": 1, "Stat2Max": 99}]
    recs, stats = _build([_row("Test Ring", "RandomSkillUnique__1")], descs=OPTION_DESCS,
                         records=OPTION_RECORDS, mods=mods, stats=OPTION_STATS,
                         indexables=INDEXABLES)
    assert "pools" not in recs[0]
    assert stats["mods_rolling_a_named_option"] == 0
