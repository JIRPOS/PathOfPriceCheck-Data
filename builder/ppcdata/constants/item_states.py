"""ClientStrings ``ItemPopup*`` ids -> what the app should do with that flag line.

An item prints a state ("Dredge", "Hinekora's Lock") as a line of its own in its flag section.
The app compiles in the flags it has rules for; every other one reaches it through the
lexicon's ``item_states`` key, so a new league's flag is a data build rather than a release.

Every short ``ItemPopup*`` string the client has lands in exactly one of the three tables
below. One that lands in none is new, is emitted as a state with no filter (the app then says
the line was not searched), and is listed by the build so someone classifies it.
"""

#: Flag lines the app reads from its compiled-in lexicon. Emitting them would change nothing.
HANDLED = {
    "ItemPopupUnidentified", "ItemPopupMirrored", "ItemPopupCorrupted",
    "ItemPopupDoubleCorrupted", "ItemPopupSplit", "ItemPopupUnmodifiable",
    "ItemPopupFracturedItem", "ItemPopupSynthesisedItem", "ItemPopupAlternateGemItem",
    "ItemPopupImbued",
    # Influences: the app reads "<influence> Item" off its influence list.
    "ItemPopupShaperItem", "ItemPopupElderItem", "ItemPopupCrusaderItem",
    "ItemPopupRedeemerItem", "ItemPopupHunterItem", "ItemPopupWarlordItem",
    "ItemPopupSearingExarchItem", "ItemPopupEaterofWorldsItem",
}

#: Strings in the family that are not a flag line on a tradeable item: labels, shop and
#: bestiary text, and bindings that keep an item off the market altogether.
NOT_STATES = {
    "ItemPopupCannotTradeOrModify", "ItemPopupLockedToAccount", "ItemPopupDroppedInMaps",
    "ItemPopupNextLevel", "ItemPopupRequirements", "ItemPopupCost", "ItemPopupFavourCost",
    "ItemPopupCostPerUnit", "ItemPopupPackExtraMonster", "ItemPopupPackExtraMonsterChance",
    "ItemPopupPackLeader",
}

#: Flag lines the app has no field for: id -> trade ``misc_filters`` key, or "" where the
#: site has none (checked against /api/trade/data/filters). A key is ticked on the search.
STATES = {
    "ItemPopupStolen": "",             # Contraband
    "ItemPopupFoilUnique": "",         # the site has foil_variation, not a foil flag
    "ItemPopupHellscaped": "",         # Scourged; scourge_tier is a range, not a flag
    "ItemPopupHinekorasLockItem": "",
    "ItemPopupDredged": "",
}
