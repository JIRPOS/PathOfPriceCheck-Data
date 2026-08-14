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


def _records(bases):
    names = sorted({b["Name"] for b in bases})
    records, _ = emit_items.build(_trade(*names), bases, [], [], [])
    return {r["name"]: r for r in records}


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


# An invitation has a row in the map device's domain and another among the quest items, and
# the clipboard prints the first: "Item Class: Misc Map Items". The stackable rule would take
# the quest row, which is what this pair exists to stop.
INVITATION = [
    _base(5100, "Writhing Invitation", "Metadata/Items/MapFragments/Primordial/QuestTangleKey",
          43),
    _base(5101, "Writhing Invitation",
          "Metadata/Items/MapFragments/Primordial/CurrencyTangleKey", 5),
]


def test_an_invitation_is_emitted_as_the_map_device_row_not_the_quest_one():
    for rows in (INVITATION, list(reversed(INVITATION))):
        rec = _records(rows)["Writhing Invitation"]
        assert rec["metadataId"] == \
            "Metadata/Items/MapFragments/Primordial/CurrencyTangleKey"
        # The whole reason the pick matters: the domain says which pool of modifiers the item
        # rolls from, and the quest row would claim it rolls from none a map can.
        assert rec["domain"] == 5


def test_a_base_carries_the_mod_domain_it_generates_from():
    recs = _records([_base(1, "Two-Stone Ring", "Metadata/Items/Rings/Ring12", 1)])
    assert recs["Two-Stone Ring"]["domain"] == 1


def test_a_trade_proxy_states_no_domain_because_it_is_not_an_item():
    # Trade lists all 491 maps under one "Map", whose game row is a stand-in sitting with the
    # stackable currency in domain 43. Copying that would tell a client every map in the game
    # rolls from the currency pool; the item class answers this record instead.
    recs = _records([_base(1, "Map", "Metadata/Items/TradeProxy/MapKey", 43)])
    assert "domain" not in recs["Map"]
    # Everything else the row says is still the best there is, and is left alone.
    assert recs["Map"]["metadataId"] == "Metadata/Items/TradeProxy/MapKey"


# One class whose bases agree on a domain, one that does not, and the proxy row that is not
# allowed a vote in either.
CLASSES = [{"_index": 0, "Name": "Maps", "Id": "Map"},
           {"_index": 1, "Name": "Jewels", "Id": "Jewel"}]
CLASS_BASES = [
    {"Id": "Metadata/Items/Maps/MapWorldsBeach", "ModDomain": 5, "ItemClassesKey": 0},
    {"Id": "Metadata/Items/Maps/MapWorldsStrand", "ModDomain": 5, "ItemClassesKey": 0},
    {"Id": "Metadata/Items/TradeProxy/MapKey", "ModDomain": 43, "ItemClassesKey": 0},
    {"Id": "Metadata/Items/Jewels/Basic", "ModDomain": 10, "ItemClassesKey": 1},
    {"Id": "Metadata/Items/Jewels/Affliction", "ModDomain": 21, "ItemClassesKey": 1},
]


def test_an_item_class_answers_for_a_domain_only_where_its_bases_agree():
    by_class = {c["itemClass"]: c
                for c in emit_items.build_classes(CLASSES, {}, CLASS_BASES)}
    # The proxy's 43 is not a vote, so the maps still agree.
    assert by_class["Maps"]["domain"] == 5
    # A class holding genuinely different things can answer for a base and never for itself.
    assert "domain" not in by_class["Jewels"]


def test_an_item_class_says_nothing_about_a_domain_with_no_bases_to_ask():
    by_class = {c["itemClass"]: c for c in emit_items.build_classes(CLASSES, {})}
    assert "domain" not in by_class["Maps"]


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


# The unique stash tab's layout, which is the only place the game says which picture goes with
# which unique name. Words holds the display name the client prints; the layout points at the
# visual identity, whose DDSFile is the path GGG's CDN serves the .png at.
WORDS = [{"Text": "Hrimsorrow"}, {"Text": "Hrimburn"}, {"Text": "Doryani's Fist"}]
VISUALS = [
    {"DDSFile": "Art/2DItems/Armours/Gloves/Hrimsorrow.dds"},
    {"DDSFile": "Art/2DItems/Armours/Gloves/Hrimburn.dds"},
    {"DDSFile": "Art/2DItems/Armours/Gloves/HrimsorrowFoil.dds"},
]
LAYOUT = [
    {"WordsKey": 0, "ItemVisualIdentityKey": 0, "IsAlternateArt": False},
    {"WordsKey": 1, "ItemVisualIdentityKey": 1, "IsAlternateArt": False},
    # The same unique with a different picture. Showing it would show the player something
    # that does not look like the item in their stash.
    {"WordsKey": 0, "ItemVisualIdentityKey": 2, "IsAlternateArt": True},
]


def test_a_unique_carries_the_path_its_artwork_is_served_at():
    art = emit_items.unique_art(LAYOUT, WORDS, VISUALS)
    # .dds in the bundle, .png on the CDN, same path — the path is emitted to be fetched.
    assert art["Hrimsorrow"] == "Art/2DItems/Armours/Gloves/Hrimsorrow.png"
    assert art["Hrimburn"] == "Art/2DItems/Armours/Gloves/Hrimburn.png"
    # No layout row, so no art: guessing a path from the name would be a 404 per item.
    assert "Doryani's Fist" not in art


def test_alternate_art_never_displaces_the_ordinary_picture():
    art = emit_items.unique_art(list(reversed(LAYOUT)), WORDS, VISUALS)
    assert art["Hrimsorrow"] == "Art/2DItems/Armours/Gloves/Hrimsorrow.png"


def test_only_uniques_are_given_art_and_only_where_there_is_some():
    trade = {"result": [{"id": "armour", "entries": [
        {"name": "Hrimsorrow", "type": "Goathide Gloves", "flags": {"unique": True}},
        {"name": "Doryani's Fist", "type": "Ambush Mitts", "flags": {"unique": True}},
        {"name": "Goathide Gloves", "type": "Goathide Gloves"},
    ]}]}
    records, stats = emit_items.build(
        trade, [], [], [], [], None, emit_items.unique_art(LAYOUT, WORDS, VISUALS))
    by_name = {r["name"]: r for r in records}
    assert by_name["Hrimsorrow"]["art"] == "Art/2DItems/Armours/Gloves/Hrimsorrow.png"
    # A unique the layout does not carry, and a plain base, which has its own art nobody asked
    # for: the client needs a picture only where it has to show *which* unique this is.
    assert "art" not in by_name["Doryani's Fist"]
    assert "art" not in by_name["Goathide Gloves"]
    assert stats["uniques_with_art"] == 1
    assert stats["uniques_without_art"] == 1


# One unique on two bases with nothing to tell them apart, and the same name a second time
# under a discriminator — trade's own shape for Stormblood and for Doryani's Delusion.
MULTI_BASE = {"result": [{"id": "flask", "entries": [
    {"name": "Stormblood", "type": "Sapphire Flask", "flags": {"unique": True}},
    {"name": "Stormblood", "type": "Topaz Flask", "flags": {"unique": True}},
    {"name": "Vessel of Vinktar", "type": "Topaz Flask", "flags": {"unique": True}},
    # Trade lists a base under several groups when it is queryable more than one way, which is
    # what the dedup is for and must keep doing.
    {"name": "Stormblood", "type": "Topaz Flask", "flags": {"unique": True}},
]}]}


def test_a_unique_on_two_bases_is_two_records():
    records, _ = emit_items.build(MULTI_BASE, [], [], [], [])
    bases = [r["unique"]["base"] for r in records if r["name"] == "Stormblood"]
    # The base -> uniques index is built from these, and it is the whole of what an
    # unidentified unique is read through: drop the second and the Topaz Flask answers with
    # one candidate, which the client takes as the name rather than as a question.
    assert bases == ["Sapphire Flask", "Topaz Flask"]
    assert len(records) == 3
