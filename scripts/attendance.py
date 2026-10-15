"""Prezence na zasedání podle EP (D1 revize, Fáze 3): prezenční listina plenárních dnů z EP Open Data.

Zdroj: EP Open Data API v2, /meetings (plenární zasedání, pole had_participant_person = prezenční listina, had_excused_person =
omluvení). Jiná metrika než „Účast na hlasování“ (ta počítá hlasy z HowTheyVote): tady jde o to, jestli byl poslanec na
jednání zapsán v prezenční listině. Počítají se jen dny, ke kterým už listina existuje, a jen v době mandátu. Omluvení se
počítají zvlášť (kdo je v listině i mezi omluvenými, je přítomen). Žádné pořadí a žádný medián EP.
"""

from __future__ import annotations

from compute_stats import in_mandate


def count_presence(days: list[dict], mep_id: int, mandates: list[dict]) -> dict:
    """{present, excused, days}: dny jednání v době mandátu, ve kterých byl poslanec v listině / omluven (a nebyl v listině)."""
    mine = [d for d in days if in_mandate(mandates, d["date"])]
    present = sum(mep_id in d["present"] for d in mine)
    excused = sum(mep_id in d["excused"] and mep_id not in d["present"] for d in mine)
    return {"present": present, "excused": excused, "days": len(mine)}
