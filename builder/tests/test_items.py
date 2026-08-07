from ppcdata.emit import items as emit_items


def _trade(*names: str) -> dict:
    """Names in the shape ``/api/trade/data/items`` returns them."""
    return {"result": [{"id": "", "entries": [{"name": n, "type": n} for n in names]}]}


def _base(index: int, name: str, ident: str, domain: int) -> dict:
    return {"_index": index, "Name": name, "Id": ident, "ModDomain": domain,
            "ItemClassesKey": 38}


def _build(bases):
    names = sorted({b["Name"] for b in bases})
    records, stats = emit_items.build(_trade(*names), bases, [], [], [])
    return {r["name"]: r.get("metadataId") for r in records}, stats


# GGG keeps the superseded row when a base is replaced, so both of these names have two rows.
# Only the live one's id is ever named by the currency-exchange feed, and the table's own
# order puts the dead one first.
SUPERSEDED = [
    _base(2973, "Sacrifice at Dawn", "Metadata/Items/MapFragments/VaalFragment1_2", 14),
    _base(2995, "Sacrifice at Dawn", "Metadata/Items/MapFragments/CurrencyVaalFragment1_2",
          43),
    # Both rows of this pair are in the stackable domain, so the id's own marker is the only
    # thing that separates them.
    _base(4681, "Echo of Trauma", "Metadata/Items/MapFragments/AtlasMemory/QuestFearKey", 43),
    _base(4682, "Echo of Trauma", "Metadata/Items/MapFragments/AtlasMemory/CurrencyFearKey",
          43),
]


def test_a_replaced_base_is_emitted_under_the_id_that_still_trades():
    ids, stats = _build(SUPERSEDED)
    assert ids["Sacrifice at Dawn"] == "Metadata/Items/MapFragments/CurrencyVaalFragment1_2"
    assert ids["Echo of Trauma"] == \
        "Metadata/Items/MapFragments/AtlasMemory/CurrencyFearKey"
    assert stats["superseded_rows_passed_over"] == 2


def test_the_live_row_wins_whichever_order_the_table_holds_it_in():
    ids, _ = _build(list(reversed(SUPERSEDED)))
    assert ids["Sacrifice at Dawn"] == "Metadata/Items/MapFragments/CurrencyVaalFragment1_2"
    assert ids["Echo of Trauma"] == \
        "Metadata/Items/MapFragments/AtlasMemory/CurrencyFearKey"


def test_rows_that_tie_keep_the_table_order():
    # Same-named bases that are both live (the Two-Stone Rings, alternate-quality gems) are
    # not what this rule is about, and it must not start reordering them.
    ids, stats = _build([
        _base(1, "Two-Stone Ring", "Metadata/Items/Rings/Ring12", 1),
        _base(2, "Two-Stone Ring", "Metadata/Items/Rings/Ring13", 1),
    ])
    assert ids["Two-Stone Ring"] == "Metadata/Items/Rings/Ring12"
    assert stats["superseded_rows_passed_over"] == 0


# The four shapes trade states a gem in. Only the transfigured ones carry a ``text``, and it
# is the name the game prints — unlike every other group, where ``text`` is a display
# composition of the other fields ("Abyssus Ezomyte Burgonet").
GEMS = {"result": [{"id": "gem", "entries": [
    {"type": "Empower Support"},
    {"type": "Vaal Blight"},
    {"type": "Raise Zombie", "text": "Raise Zombie of Falling", "disc": "alt_y"},
    {"type": "Vaal Blight", "text": "Vaal Blight (Blight of Atrophy)", "disc": "alt_y"},
]}]}


def test_a_gem_is_keyed_on_the_name_the_game_prints():
    records, stats = emit_items.build(GEMS, [], [], [], [])
    by_name = {r["name"]: r for r in records}

    # A transfigured gem: the clipboard prints this name and nothing else, and trade will only
    # answer to the skill it alters plus the discriminator.
    assert by_name["Raise Zombie of Falling"]["tradeName"] == "Raise Zombie"
    assert by_name["Raise Zombie of Falling"]["tradeDisc"] == "alt_y"
    # A transfigured Vaal gem is stated as the pair, which is what the client rebuilds from
    # the two names the clipboard prints.
    assert by_name["Vaal Blight (Blight of Atrophy)"]["tradeName"] == "Vaal Blight"
    # An ordinary gem is queried under the name it prints, so it carries no second one.
    assert "tradeName" not in by_name["Empower Support"]
    assert "tradeName" not in by_name["Vaal Blight"]
    assert stats["gems_keyed_on_display_name"] == 2


def test_a_display_name_outside_the_gem_group_is_left_alone():
    # Trade's ``text`` elsewhere is a composition, never a name the game prints: keying a
    # unique on "Abyssus Ezomyte Burgonet" would make it unfindable from the item text.
    unique = {"result": [{"id": "armour", "entries": [
        {"type": "Ezomyte Burgonet", "text": "Abyssus Ezomyte Burgonet", "name": "Abyssus",
         "flags": {"unique": True}}]}]}
    records, stats = emit_items.build(unique, [], [], [], [])
    assert records[0]["name"] == "Abyssus"
    assert "tradeName" not in records[0]
    assert stats["gems_keyed_on_display_name"] == 0
