"""Projevy v plénu českých poslanců (D1 revize, Fáze 3): čisté funkce nad data/speeches.json.

Zdroj: EP Open Data API v2, endpoint /speeches (CC BY 4.0). Počítá se jen v době mandátu (stejně jako účast na hlasování).
Typy podle zdroje: ústní projev v rozpravě (PLENARY_DEBATE_SPEECH) a písemné prohlášení (PLENARY_DEBATE_WRITTEN_STATEMENT).
Písemná prohlášení se dají psát hromadně, proto se počítají zvlášť a do „projevů“ se nesčítají. Délka projevu je rozdíl
časových značek ve zdroji; chybí-li, projev se počítá, ale do délky ne.

Žádné skóre a žádné pořadí: projevy jsou počet a čas, ne měřítko kvality. Medián EP se neuvádí (stáhnout projevy všech
720 poslanců EP by znamenalo ~1 500 dotazů týdně).
"""

from __future__ import annotations

import datetime as dt

from compute_stats import in_mandate

TYPES = {
    "def/ep-activities/PLENARY_DEBATE_SPEECH": "speech",
    "def/ep-activities/PLENARY_DEBATE_WRITTEN_STATEMENT": "written_statement",
}


def minutes_between(start: str | None, end: str | None) -> float | None:
    """Délka v minutách ze dvou ISO časových značek; None, když některá chybí nebo je konec před začátkem."""
    if not start or not end:
        return None
    try:
        a, b = dt.datetime.fromisoformat(start), dt.datetime.fromisoformat(end)
    except ValueError:
        return None
    return round((b - a).total_seconds() / 60, 2) if b >= a else None


def count_activity(rows: list[dict], mandates: list[dict]) -> dict:
    """Projevy poslance v době mandátu: počet ústních projevů, jejich celková délka (jen u těch se známou délkou),
    počet bodů jednání, ve kterých vystoupil, a zvlášť počet písemných prohlášení."""
    speeches = [r for r in rows if r["type"] == "speech" and in_mandate(mandates, r["date"])]
    written = [r for r in rows if r["type"] == "written_statement" and in_mandate(mandates, r["date"])]
    timed = [r["minutes"] for r in speeches if r.get("minutes") is not None]
    return {
        "speeches": len(speeches),
        "speeches_minutes": round(sum(timed), 1),
        "speeches_timed": len(timed),
        "speech_items": len({r["item"] for r in speeches if r.get("item")}),
        "written_statements": len(written),
    }
