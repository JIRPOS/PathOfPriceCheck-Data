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


def test_a_literal_sign_in_the_description_is_folded_into_the_placeholder():
    # GGG writes this one's sign as literal text — `"+{0}% Monster Chaos Resistance"` — where
    # `{0:+d} to maximum Life` hides it in the format spec. The client cannot tell those apart:
    # a sign is part of the number token, so `+25% Monster Chaos Resistance` off the clipboard
    # normalizes to `#% …` and a record emitted as `+#% …` is indexed under a key no item text
    # can produce. It was the whole monster-resistance family, unreachable.
    d = Description(
        stat_ids=["map_monster_chaos_resistance_%"],
        variants=[Variant(ranges=["#"], text="+#% Monster Chaos Resistance")],
    )
    trade = _trade(("explicit", "explicit.stat_1", "+#% Monster Chaos Resistance"))
    records, _ = _build(trade, [d])

    assert _strings(records[0]) == ["#% Monster Chaos Resistance"]
    assert records[0]["ref"] == "#% Monster Chaos Resistance"


def test_a_class_specific_wording_joins_the_same_stat_id_from_another_file():
    # heist_contract_npc_cost_+% is worded two ways depending on where it rolled: the main
    # file's "of Rogues" phrasing, which is also trade's own canonical text, and
    # heist_equipment_stat_descriptions.txt's bare phrasing, which is what a Heist Gear item
    # actually prints. statdesc.parse runs once per file, so these arrive as two Description
    # objects sharing a stat id rather than one — and before the merge, only the file whose
    # wording trade matched ever became part of a record, so the bare phrasing joined nothing
    # and a rare Heist Gear item's own "reduced Hiring Fee" line came back unrecognised.
    main = Description(
        stat_ids=["heist_contract_npc_cost_+%"],
        variants=[
            Variant(ranges=["1|#"], text="#% increased Hiring Fee of Rogues"),
            Variant(ranges=["#|-1"], text="#% reduced Hiring Fee of Rogues", negate=True),
        ],
    )
    heist_equipment = Description(
        stat_ids=["heist_contract_npc_cost_+%"],
        variants=[
            Variant(ranges=["1|#"], text="#% increased Hiring Fee"),
            Variant(ranges=["#|-1"], text="#% reduced Hiring Fee", negate=True),
        ],
    )
    trade = _trade(("explicit", "explicit.stat_2257592286", "#% increased Hiring Fee of Rogues"))
    records, st = _build(trade, [main, heist_equipment])

    rec = _by_id(records, "explicit.stat_2257592286")
    assert rec["ref"] == "#% increased Hiring Fee of Rogues"
    assert "#% increased Hiring Fee" in _strings(rec)
    assert "#% reduced Hiring Fee" in _strings(rec)
    assert st["wordings_ambiguous_in_a_namespace"] == []


def test_a_reused_stat_id_does_not_hand_one_wording_to_two_records():
    # critical_strike_chance_+% is real: the main file words it "Global Critical Strike
    # Chance" and the gem file's "Supported Skills have..." variant genuinely belongs beside
    # it. But heist_equipment_stat_descriptions.txt also reuses that same id for a bare
    # "Critical Strike Chance" wording that happens to collide letter-for-letter with a
    # *different* id's own text (local_critical_strike_chance_+%, trade-matched on its own).
    # Folding every same-id block together handed that bare wording to both records — the
    # exact shape the client refuses to resolve.
    main = Description(
        stat_ids=["critical_strike_chance_+%"],
        variants=[
            Variant(ranges=["1|#"], text="#% increased Global Critical Strike Chance"),
            Variant(ranges=["#|-1"], text="#% reduced Global Critical Strike Chance",
                    negate=True),
        ],
    )
    gem = Description(
        stat_ids=["critical_strike_chance_+%"],
        variants=[
            Variant(ranges=["1|#"], text="Supported Skills have #% increased Critical "
                                        "Strike Chance"),
            Variant(ranges=["#|-1"], text="Supported Skills have #% reduced Critical Strike "
                                        "Chance", negate=True),
        ],
    )
    heist_equipment = Description(
        stat_ids=["critical_strike_chance_+%"],
        variants=[
            Variant(ranges=["1|#"], text="#% increased Critical Strike Chance"),
            Variant(ranges=["#|-1"], text="#% reduced Critical Strike Chance", negate=True),
        ],
    )
    local = Description(
        stat_ids=["local_critical_strike_chance_+%"],
        variants=[
            Variant(ranges=["1|#"], text="#% increased Critical Strike Chance"),
            Variant(ranges=["#|-1"], text="#% reduced Critical Strike Chance", negate=True),
        ],
    )
    trade = _trade(
        ("explicit", "explicit.stat_587431675", "#% increased Global Critical Strike Chance"),
        ("explicit", "explicit.stat_2375316951", "#% increased Critical Strike Chance"),
    )
    # Parse order matters here, the same as it does for the real files: both of the main file's
    # blocks (global and local) come before the gem and heist-equipment files that reuse
    # `critical_strike_chance_+%`'s id for their own wordings.
    records, st = _build(trade, [main, local, gem, heist_equipment])

    glob = _by_id(records, "explicit.stat_587431675")
    bare = _by_id(records, "explicit.stat_2375316951")
    assert "Supported Skills have #% increased Critical Strike Chance" in _strings(glob)
    assert "#% increased Critical Strike Chance" not in _strings(glob)
    assert _strings(bare) == ["#% increased Critical Strike Chance",
                              "#% reduced Critical Strike Chance"]
    assert st["wordings_ambiguous_in_a_namespace"] == []


def test_folding_the_sign_keeps_the_plain_wording_over_the_negate_one():
    # Once the sign is gone these two say the same thing, because the sign the client reads is
    # the number's own. Keeping the negate entry would flip a printed -40 back to +40 — an
    # unfindable stat traded for a wrong one.
    d = Description(
        stat_ids=["evasion_rating_while_in_sand_stance"],
        variants=[
            Variant(ranges=["#"], text="+# to Evasion Rating while in Sand Stance"),
            Variant(ranges=["#"], text="-# to Evasion Rating while in Sand Stance", negate=True),
        ],
    )
    trade = _trade(("explicit", "explicit.stat_2", "+# to Evasion Rating while in Sand Stance"))
    records, _ = _build(trade, [d])

    assert _strings(records[0]) == ["# to Evasion Rating while in Sand Stance"]
    assert "negate" not in records[0]["matchers"][0]
