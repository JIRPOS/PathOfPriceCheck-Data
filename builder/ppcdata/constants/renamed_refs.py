"""Pool wordings GGG reworded without changing the modifier: old ref -> current ref.

The app's map-check verdicts are keyed on a stat's ``ref``, so a reworded stat would orphan
every verdict on it. This table carries them across. ``notes`` proposes candidates on every
build (``emit.renamed_refs.detect``); a person decides, because a reworded line can also be a
different modifier wearing the old one's ids.
"""

#: Accumulates across leagues: a table written two leagues ago still names the oldest wording.
#: Keep it a superset of the app's compiled-in ``kRenamed``: the app applies that one first, so
#: removing an entry here does not undo the rename in any app.
RENAMED = {
    # 3.30
    "#% more Scarabs found in Area": "#% more Threads found in Area",
    "Final Boss drops # additional Scarab Items": "Final Boss drops # additional Threads",
    "Area contains an additional Abyss": "Area contains # additional Abysses",
    "Areas contain a Mirror of Delirium": "Area contains a Mirror of Delirium",
    "Players in Area take #% increased Damage per nearby Ally":
        "Players in Area take #% increased Damage per Ally within 6 metres",
    "This Map's Modifiers to Quantity of Items found also apply to Rarity":
        "This Map's Modifiers to Atlas Drops also apply to Item Rarity",
}

#: Detected candidates that are a different decision, not a new wording; never proposed again.
NOT_RENAMED = {
    # 3.30: a chart's essence-imprisoned rares became Calcified ones.
    "Rare monsters that are natural inhabitants are imprisoned by Essences":
        "Rare monsters that are natural inhabitants are Calcified",
}
