from ppcdata.constants.item_states import HANDLED, NOT_STATES, STATES
from ppcdata.emit import lexicon as emit_lexicon


def _rows(**strings):
    return [{"Id": k, "Text": v} for k, v in strings.items()]


def test_only_states_the_app_has_no_field_for_are_emitted():
    doc, report = emit_lexicon.build(_rows(
        ItemPopupCorrupted="Corrupted",
        ItemPopupRequirements="Requirements",
        ItemPopupDredged="Dredge",
        ItemPopupCost="Cost:",
        ItemPopupSomethingNew="Haunted",
        ItemPopupLongProse="{0} can be used to {1}",
        ItemDisplayStackSize="Stack Size: "), "en")
    assert doc["language"] == "en"
    assert set(doc) == {"language", "item_states"}
    assert doc["item_states"] == [
        {"text": "Dredge", "trade_filter": "", "filter": False},
        {"text": "Haunted", "trade_filter": "", "filter": False},
    ]
    assert report["unclassified"] == ["ItemPopupSomethingNew = 'Haunted'"]
    assert "ItemPopupStolen" in report["missing"]


def test_a_mapped_filter_is_ticked(monkeypatch):
    monkeypatch.setitem(STATES, "ItemPopupDredged", "dredged")
    doc, _ = emit_lexicon.build(_rows(ItemPopupDredged="Dredge"), "en")
    assert doc["item_states"] == [{"text": "Dredge", "trade_filter": "dredged", "filter": True}]


def test_the_tables_do_not_overlap():
    assert not (HANDLED & NOT_STATES)
    assert not (HANDLED & STATES.keys())
    assert not (NOT_STATES & STATES.keys())
