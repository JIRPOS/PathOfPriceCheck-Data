from ppcdata.normalize import candidates, placeholder_form, scan_numbers


def test_sign_is_part_of_the_token():
    # "+42" is one token, so the generic form has no leading '+'. This is why the builder
    # strips '+#' from GGG's trade text before joining.
    assert placeholder_form("+42 to maximum Life") == "# to maximum Life"
    assert placeholder_form("-20% to Fire Resistance") == "#% to Fire Resistance"


def test_lookbehind_keeps_ranges_from_splitting():
    # Without the "not preceded by a digit" rule, "1-30" scans as 1 and -30.
    toks = scan_numbers("Grants 1-30 Life per Enemy Hit")
    assert [t.value for t in toks] == [1.0, 30.0]
    assert placeholder_form("Grants 1-30 Life per Enemy Hit") == "Grants #-# Life per Enemy Hit"


def test_advanced_mod_description_ranges_are_absorbed():
    assert (placeholder_form("Adds 5(4-6) to 12(10-14) Physical Damage")
            == "Adds # to # Physical Damage")
    toks = scan_numbers("Adds 5(4-6) to 12(10-14) Physical Damage")
    assert [(t.value, t.bound_min, t.bound_max) for t in toks] == [(5, 4, 6), (12, 10, 14)]


def test_negative_lower_bound_does_not_split_at_its_sign():
    # "(-20-10)" is min -20, max 10 — the first character of the minimum is exempt from the
    # "not a '-'" rule precisely so this works.
    toks = scan_numbers("+5(-20-10)% to something")
    assert len(toks) == 1
    assert (toks[0].bound_min, toks[0].bound_max) == (-20.0, 10.0)


def test_decimals_are_counted():
    toks = scan_numbers("0.5% of Physical Attack Damage Leeched as Life")
    assert toks[0].decimals == 1
    assert toks[0].value == 0.5


def test_candidate_order_is_most_generic_first():
    cs = candidates("Adds 5 to 12 Physical Damage")
    assert cs[0] == "Adds # to # Physical Damage"
    assert cs[-1] == "Adds 5 to 12 Physical Damage"
    assert cs == ["Adds # to # Physical Damage", "Adds # to 12 Physical Damage",
                  "Adds 5 to # Physical Damage", "Adds 5 to 12 Physical Damage"]


def test_wording_with_no_numbers_yields_itself():
    assert candidates("No Physical Damage") == ["No Physical Damage"]


def test_empty_parens_are_stripped():
    assert placeholder_form("Something ()odd") == "Something odd"


def test_candidates_are_deduplicated_but_ordered():
    cs = candidates("+42 to maximum Life")
    assert cs == ["# to maximum Life", "+42 to maximum Life"]
    assert len(cs) == len(set(cs))
