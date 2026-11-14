import textwrap

from ppcdata import statdesc
from ppcdata.emit.stats import join_key

# A faithful slice of the real file: the block that gave both the negate wording and the
# fixed-value one for local physical damage.
SAMPLE = textwrap.dedent("""\
    description
    \t2 local_physical_damage_+% local_weapon_no_physical_damage
    \t5
    \t\t# 1|# "No Physical Damage"
    \t\t# #|-1 "No Physical Damage"
    \t\t#|-100 # "No Physical Damage"
    \t\t1|# 0 "{0}% increased Physical Damage"
    \t\t-99|-1 0 "{0}% reduced Physical Damage" negate 1
    \tlang "German"
    \t5
    \t\t1|# 0 "{0}% erhöhter physischer Schaden"

    description
    \t1 base_maximum_life
    \t1
    \t\t# "{0:+d} to maximum Life"
    """)


def _parse(tmp_path, text=SAMPLE):
    p = tmp_path / "stat_descriptions.txt"
    p.write_text(text, encoding="utf-16")
    return statdesc.parse(str(p))


def test_parses_blocks_and_ignores_other_languages(tmp_path):
    descs = _parse(tmp_path)
    assert len(descs) == 2
    assert descs[0].stat_ids == ["local_physical_damage_+%", "local_weapon_no_physical_damage"]
    assert descs[1].stat_ids == ["base_maximum_life"]
    # The German variant must not leak in as a wording.
    assert all("erhöhter" not in v.text for v in descs[0].variants)


def test_placeholders_become_hashes(tmp_path):
    descs = _parse(tmp_path)
    assert descs[1].variants[0].text == "# to maximum Life"


def test_primary_variant_skips_leading_special_cases(tmp_path):
    # The block opens with three "No Physical Damage" forms; the stat's own wording is the
    # first that shows a number and is not a negation.
    d = _parse(tmp_path)[0]
    assert statdesc.primary_variant(d).text == "#% increased Physical Damage"


def test_negate_and_implied_value_are_captured(tmp_path):
    d = _parse(tmp_path)[0]
    by_text = {}
    for v in d.variants:
        by_text.setdefault(v.text, []).append(v)
    assert any(v.negate for v in by_text["#% reduced Physical Damage"])
    # "#|-100" means the wording stands for a -100 roll.
    assert any(v.fixed_value == -100.0 for v in by_text["No Physical Damage"])


def test_every_wording_is_indexed_not_just_the_first(tmp_path):
    idx = statdesc.by_english_text(_parse(tmp_path))
    for wording in ("#% increased Physical Damage", "#% reduced Physical Damage",
                    "No Physical Damage", "# to maximum Life"):
        assert wording in idx, wording


def test_join_key_strips_the_trade_side_plus():
    # Trade writes "+# to maximum Life"; the game's {0:+d} folds the sign into the number.
    assert join_key("+# to maximum Life") == "# to maximum Life"
    assert join_key("# to maximum Life") == "# to maximum Life"
    # A '+' that is not in front of a placeholder is left alone.
    assert join_key("Adds # to # Fire Damage") == "Adds # to # Fire Damage"


MULTILINE = textwrap.dedent("""\
    description
    \t1 hinekora_rotating_buff
    \t1
    \t\t# "Every 5 seconds, gain one of the following:\\nYour Hits are always Critical Strikes"
    description
    \t2 random_skill_gem_level random_skill_gem_index
    \t1
    \t\t1|# # "+{0} to Level of all {1} Gems" display_indexable_skill 2
    description
    \t3 pearl_slot pearl_index pearl_level
    \t1
    \t\t1 # # "Skills Socketed in your Helmet are Supported by level {2} {1}" \\
display_indexable_non_active_support 2
    description
    \t1 maximum_number_of_X_minion_type_doubled
    \t1
    \t\t# "Maximum number of {0} is Doubled\\nCannot have Minions other than {0}" \\
minion_doubling_type 1
    """)


def _parse_multiline(tmp_path):
    p = tmp_path / "multi.txt"
    p.write_text(MULTILINE.replace(" \\\n", " "), encoding="utf-16")
    return statdesc.parse(str(p))


def test_a_line_break_is_decoded_not_left_as_an_escape(tmp_path):
    # The trade text carries a real break, so a wording left as backslash-n joins to nothing —
    # and every multi-line modifier loses its negate, fixed-value and trade id because of it.
    d = _parse_multiline(tmp_path)[0]
    assert "\\n" not in d.variants[0].text
    assert d.variants[0].text.count("\n") == 1


def test_a_placeholder_remembers_which_stat_fills_it(tmp_path):
    level, pearl = _parse_multiline(tmp_path)[1], _parse_multiline(tmp_path)[2]
    assert level.variants[0].text == "+# to Level of all # Gems"
    assert level.variants[0].placeholders == [0, 1]
    assert level.variants[0].indexable == ("skill", 1)
    # This one prints its two stats in the opposite order to the order it lists them, which is
    # the whole reason the numbering is kept rather than counted.
    assert pearl.variants[0].placeholders == [2, 1]
    assert pearl.variants[0].indexable == ("support", 1)


def test_a_range_spec_pins_a_variant_or_spans_values():
    assert statdesc.pinned_value("3") == 3
    assert statdesc.pinned_value("1|#") is None
    assert statdesc.pinned_value("#") is None
    # "+#" against "-#": the two halves of one description, told apart by their specs.
    assert statdesc.spec_accepts("1|#", 3, 3)
    assert not statdesc.spec_accepts("#|-1", 3, 3)
    assert statdesc.spec_accepts("#", 3, 3)


# Real 3.30 blocks. The skill's level appears inside the link key as well as in the text, and
# only the one in the text is a number the client prints.
MARKUP = textwrap.dedent("""\
    description
    \t1 local_display_grants_restless_dead_skill_level_x
    \t1
    \t\t1|# "Trigger level {0} [CeaselessFleshUnique::{0}|Ceaseless Flesh] once every second"
    description
    \t1 local_display_grants_skill_battlemages_cry_level
    \t1
    \t\t# "Grants Level {0} [BattlemagesCry<gemlevel={0}>|Battlemage's Cry] Skill"
    description
    \t1 local_display_socketed_golem_skill_grants_onslaught_when_summoned
    \t1
    \t\t# "Gain [Onslaught] for {0} seconds when you Cast Socketed Golem Skill" milliseconds_to_seconds 1
    description
    \t1 local_display_grants_skill_oozing_aura_level
    \t1
    \t\t# "[DNT] Grants Level {0} Oozing Aura Skill"
    """)


def test_link_markup_keeps_only_what_the_client_prints(tmp_path):
    texts = [d.variants[0].text for d in _parse(tmp_path, MARKUP)]
    assert texts[:3] == [
        "Trigger level # Ceaseless Flesh once every second",
        "Grants Level # Battlemage's Cry Skill",
        "Gain Onslaught for # seconds when you Cast Socketed Golem Skill",
    ]


def test_a_placeholder_inside_a_link_key_is_not_counted(tmp_path):
    descs = _parse(tmp_path, MARKUP)
    assert descs[0].variants[0].placeholders == [0]
    assert descs[1].variants[0].placeholders == [0]


def test_dnt_stays_so_it_cannot_pass_for_a_live_wording(tmp_path):
    assert _parse(tmp_path, MARKUP)[3].variants[0].text == "[DNT] Grants Level # Oozing Aura Skill"


def test_a_minion_type_is_a_row_number_printed_twice(tmp_path):
    # 3.30 folded The Dark Monarch's sixteen wordings into this one.
    d = _parse_multiline(tmp_path)[3]
    assert d.variants[0].text == "Maximum number of # is Doubled\nCannot have Minions other than #"
    assert d.variants[0].placeholders == [0, 0]
    assert d.variants[0].indexable == ("minion_doubling", 0)
