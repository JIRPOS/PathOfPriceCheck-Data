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
