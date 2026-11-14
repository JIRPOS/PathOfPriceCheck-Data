"""``<lang>-lexicon.json`` — the client's own words the app cannot compile in.

The app's lexicon overlays this file on its English table, and the ``lists``,
``properties`` and ``item_classes`` keys *replace* what they name. So this emits only keys
with no compiled-in counterpart: today, ``item_states``.
"""

from __future__ import annotations

from ..constants.item_states import HANDLED, NOT_STATES, STATES

PREFIX = "ItemPopup"


def _is_flag_like(text: str) -> bool:
    # A flag line is a short, whole line: no placeholder, no label colon, no wrap.
    return (0 < len(text) < 40 and "{" not in text and "\n" not in text
            and not text.rstrip().endswith(":") and text == text.strip())


def build(client_strings: list[dict], lang: str) -> tuple[dict, dict]:
    """The lexicon document and a report: ``{"unclassified": [...], "missing": [...]}``.

    ``unclassified`` are new flag-like strings no table names (emitted, with no filter);
    ``missing`` are ids a table names that the client no longer has.
    """
    by_id = {r["Id"]: r["Text"] for r in client_strings if r.get("Id")}
    states, unclassified = [], []
    for sid, text in by_id.items():
        if not sid.startswith(PREFIX) or not _is_flag_like(text or ""):
            continue
        if sid in HANDLED or sid in NOT_STATES:
            continue
        if sid in STATES:
            f = STATES[sid]
            states.append({"text": text, "trade_filter": f, "filter": bool(f)})
        else:
            unclassified.append(f"{sid} = {text!r}")
            states.append({"text": text, "trade_filter": "", "filter": False})
    states.sort(key=lambda s: s["text"])
    missing = sorted((HANDLED | NOT_STATES | STATES.keys()) - by_id.keys())
    return ({"language": lang, "item_states": states},
            {"unclassified": sorted(unclassified), "missing": missing})
