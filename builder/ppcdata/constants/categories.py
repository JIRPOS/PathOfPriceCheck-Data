"""ItemClasses.Id -> trade `type_filters.filters.category.option`.

The clipboard prints ``Item Class: Rings``; ``ItemClasses.Name`` is already that plural
form, so the join to game data needs no table. What *does* need a table is the last hop to
the trade site's category slug, because neither source states the correspondence.

Option ids were read from /api/trade/data/filters. Classes with no sensible trade category
are simply absent; the emitter writes an empty string and the client treats that as "don't
constrain the category".
"""

TRADE_CATEGORY_BY_CLASS_ID = {
    # Weapons
    "Bow": "weapon.bow",
    "Claw": "weapon.claw",
    "Dagger": "weapon.basedagger",
    "Rune Dagger": "weapon.runedagger",
    "One Hand Axe": "weapon.oneaxe",
    "One Hand Mace": "weapon.basemace",
    "One Hand Sword": "weapon.basesword",
    "Thrusting One Hand Sword": "weapon.rapier",
    "Sceptre": "weapon.sceptre",
    "Staff": "weapon.basestaff",
    "Warstaff": "weapon.warstaff",
    "Two Hand Axe": "weapon.twoaxe",
    "Two Hand Mace": "weapon.twomace",
    "Two Hand Sword": "weapon.twosword",
    "Wand": "weapon.wand",
    "FishingRod": "weapon.rod",
    # Armour
    "Body Armour": "armour.chest",
    "Boots": "armour.boots",
    "Gloves": "armour.gloves",
    "Helmet": "armour.helmet",
    "Shield": "armour.shield",
    "Quiver": "armour.quiver",
    # Accessories
    "Amulet": "accessory.amulet",
    "Belt": "accessory.belt",
    "Ring": "accessory.ring",
    "Trinket": "accessory.trinket",
    # Gems
    "Active Skill Gem": "gem.activegem",
    "Support Skill Gem": "gem.supportgem",
    # Jewels
    "Jewel": "jewel.base",
    "AbyssJewel": "jewel.abyss",
    # Flasks — trade has one bucket for all of them.
    "LifeFlask": "flask",
    "ManaFlask": "flask",
    "HybridFlask": "flask",
    "UtilityFlask": "flask",
    "UtilityFlaskCritical": "flask",
    # Maps and fragments
    "Map": "map",
    "MapFragment": "map.fragment",
    "Breachstone": "map.breachstone",
    "MiscMapItem": "map.fragment",
    # Misc
    "DivinationCard": "card",
    "Leaguestone": "leaguestone",
    "Contract": "heistmission.contract",
    "Blueprint": "heistmission.blueprint",
    "HeistEquipmentWeapon": "heistequipment.heistweapon",
    "HeistEquipmentTool": "heistequipment.heisttool",
    "HeistEquipmentUtility": "heistequipment.heistutility",
    "HeistEquipmentReward": "heistequipment.heistreward",
    "Incubator": "currency.incubator",
    "DelveStackableSocketableCurrency": "currency.fossil",
    "StackableCurrency": "currency",
    "Currency": "currency",
    "Tincture": "tincture",
    "Corpse": "corpse",
    "Idol": "idol",
    "SanctumSpecialRelic": "sanctum.relic",
    "SanctumRelic": "sanctum.relic",
    "ExpeditionLogbook": "logbook",
}
