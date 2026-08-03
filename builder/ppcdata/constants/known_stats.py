"""Hand-maintained facts the source data does not express.

Keep this small and justified. Everything here is a maintenance cost that has to be
re-checked when GGG rewords a stat — which is why the build **fails** when an entry here
matches no record. A table that silently matches nothing reads as if it were working.

Every ref below is the *primary wording the game renders*, which is not always the one the
trade site shows: the stat trade indexes as "increased Action Speed" is worded by the game
as "#% reduced Action Speed", because on gear it only ever appears as a downside.
"""

# Stats where a higher roll is worse, so a search should bound the maximum rather than the
# minimum. Neither the trade API nor stat_descriptions says which direction is desirable,
# so this cannot be derived; the default is +1 and only exceptions live here.
BETTER_MINUS_ONE = {
    "#% increased Attribute Requirements",
    "Items and Gems have #% increased Attribute Requirements",
    "# to Total Mana Cost of Skills",
    "#% increased Flask Charges used",
    "#% increased Effect of Curses on you",
    "#% increased Damage taken",
    "#% chance to be Ignited",
    "#% chance to be Shocked",
    "#% chance to be Frozen, Shocked and Ignited",
    "#% reduced Action Speed",
}

# Stats the trade site indexes with the opposite sign from the game's wording, so a filter
# has to flip the sign and swap min/max when building the query.
TRADE_INVERTED = {
    "#% reduced Action Speed",
}
