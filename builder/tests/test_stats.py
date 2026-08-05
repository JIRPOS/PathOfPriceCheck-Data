from ppcdata.emit import stats as emit_stats
from ppcdata.statdesc import Description, Variant


def _trade(*entries: tuple[str, str, str]) -> dict:
    """``(group, id, text)`` triples in the shape ``/api/trade/data/stats`` returns."""
    groups: dict[str, list[dict]] = {}
    for group, sid, text in entries:
        groups.setdefault(group, []).append({"id": sid, "text": text, "type": group})
    return {"result": [{"id": g, "entries": e} for g, e in groups.items()]}


def _build(trade, descs):
    return emit_stats.build(trade, descs, {}, set())


def _by_id(records, sid):
    return next(r for r in records
                if any(sid in ids for ids in r["trade"]["ids"].values()))


def _strings(rec):
    return [m["string"] for m in rec["matchers"]]


# The Surgeon's flask prefix. One game description renders both wordings; trade indexes each
# under its own hash, so both become records — and both used to claim both wordings, which the
# client cannot resolve and drops.
FLASK_CHARGE = Description(
    stat_ids=["flask_charge_on_crit_%"],
    variants=[
        Variant(ranges=["1|99"], text="#% chance to gain a Flask Charge when you deal a "
                                      "Critical Strike"),
        Variant(ranges=["100|100"], text="Gain a Flask Charge when you deal a Critical Strike",
                fixed_value=100.0),
    ],
)


def test_a_wording_trade_indexes_separately_belongs_to_one_record():
    trade = _trade(
        ("explicit", "explicit.stat_3738001379",
         "#% chance to gain a Flask Charge when you deal a Critical Strike"),
        ("explicit", "explicit.stat_1546046884",
         "Gain a Flask Charge when you deal a Critical Strike"),
    )
    records, st = _build(trade, [FLASK_CHARGE])

    rolled = _by_id(records, "explicit.stat_3738001379")
    always = _by_id(records, "explicit.stat_1546046884")
    assert _strings(rolled) == ["#% chance to gain a Flask Charge when you deal a Critical Strike"]
    assert _strings(always) == ["Gain a Flask Charge when you deal a Critical Strike"]
    # The 100% wording still says what it implies; that is the only way a roll comes out of it.
    assert always["matchers"][0]["value"] == 100.0
    assert st["wordings_ambiguous_in_a_namespace"] == []
    assert st["narrowed_to_own_wordings"] == 2


def test_a_wording_trade_does_not_index_stays_on_every_record():
    # Trade has no hash for the "reduced" phrasing — it indexes the stat as a negative
    # "increased" — so that matcher is not contested and must survive.
    d = Description(
        stat_ids=["physical_damage_+%"],
        variants=[
            Variant(ranges=["1|#"], text="#% increased Global Physical Damage"),
            Variant(ranges=["-99|-1"], text="#% reduced Global Physical Damage", negate=True),
        ],
    )
    trade = _trade(("explicit", "explicit.stat_1", "#% increased Global Physical Damage"))
    records, _ = _build(trade, [d])

    assert len(records) == 1
    assert _strings(records[0]) == ["#% increased Global Physical Damage",
                                    "#% reduced Global Physical Damage"]
    assert records[0]["matchers"][1]["negate"] is True
    assert records[0]["ref"] == "#% increased Global Physical Damage"


def test_the_record_keyed_by_the_inverse_wording_owns_it_and_is_not_negated():
    # Trade hashes "Lose #% of Life on Kill" itself, and that hash indexes the number as
    # printed. A record whose only wording is the inverse one is not the inverse of anything.
    d = Description(
        stat_ids=["life_gain_per_target"],
        variants=[
            Variant(ranges=["1|#"], text="Recover #% of Life on Kill"),
            Variant(ranges=["#|-1"], text="Lose #% of Life on Kill", negate=True),
        ],
    )
    trade = _trade(
        ("explicit", "explicit.stat_2023107756", "Recover #% of Life on Kill"),
        ("explicit", "explicit.stat_751813227", "Lose #% of Life on Kill"),
    )
    records, st = _build(trade, [d])

    lose = _by_id(records, "explicit.stat_751813227")
    assert lose["ref"] == "Lose #% of Life on Kill"
    assert "negate" not in lose["matchers"][0]
    assert _by_id(records, "explicit.stat_2023107756")["ref"] == "Recover #% of Life on Kill"
    assert st["wordings_ambiguous_in_a_namespace"] == []


def test_an_option_stat_becomes_one_record_per_option_wording():
    d = Description(
        stat_ids=["map_atlas_influence"],
        variants=[
            Variant(ranges=["1|1"], text="Area is influenced by The Shaper", fixed_value=1.0),
            Variant(ranges=["2|2"], text="Area is influenced by The Elder", fixed_value=2.0),
        ],
    )
    trade = _trade(
        ("implicit", "implicit.stat_1792283443|1", "Area is influenced by The Shaper"),
        ("implicit", "implicit.stat_1792283443|2", "Area is influenced by The Elder"),
    )
    records, st = _build(trade, [d])

    elder = _by_id(records, "implicit.stat_1792283443|2")
    assert elder["ref"] == "Area is influenced by The Elder"
    assert _strings(elder) == ["Area is influenced by The Elder"]
    assert st["wordings_ambiguous_in_a_namespace"] == []


def test_a_wording_with_no_description_keeps_the_trade_text():
    trade = _trade(("pseudo", "pseudo.pseudo_total_life", "+# total maximum Life"))
    records, st = _build(trade, [])

    # The join key, i.e. trade's own wording with the sign folded into the placeholder the way
    # the game writes it.
    assert _strings(records[0]) == ["# total maximum Life"]
    assert st["unmatched"] == 1
