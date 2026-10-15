"""Hlasování podle kategorií (tabulka „Podle témat“): počty a chování českých poslanců v každé kategorii.

Kategorie jsou pevná pravidla nad tématy OEIL (scripts/categories.py), žádná AI. Hlasování může spadat do víc kategorií
(počítá se do každé z nich), hlasování bez tématu OEIL je v řádku „Bez tématu“. Čísla jsou čisté počty z dat HowTheyVote,
bez pořadí a bez hodnocení; „Češi jednotně“ se počítá stejně jako v compute_stats.analyze_votes (aspoň dva Češi pro/proti).
"""

from __future__ import annotations

from categories import CATEGORIES, categories_for
from compute_stats import active_positions
from vote_kinds import is_final

POSITIONS = ["FOR", "AGAINST", "ABSTENTION", "DID_NOT_VOTE"]
NONE_KEY = "none"


def category_stats(votes: list[dict], meps_by_id: dict) -> dict:
    """{"categories": [{key, label, votes, final, cz_united_final: [x, z], cz_final: [pro, proti, zdržel, nehlasoval],
    cz_attendance: [hlasovali, celkem]}], "votes_total", "period"} v pořadí z CATEGORIES, „Bez tématu“ na konci."""
    rows = {k: {"key": k, "label": n, "votes": 0, "final": 0, "cz_united_final": [0, 0], "cz_final": [0, 0, 0, 0],
                "cz_attendance": [0, 0]} for k, n, _ in CATEGORIES}
    rows[NONE_KEY] = {"key": NONE_KEY, "label": "Bez tématu", "votes": 0, "final": 0, "cz_united_final": [0, 0],
                      "cz_final": [0, 0, 0, 0], "cz_attendance": [0, 0]}
    for v in votes:
        keys = categories_for(v) or [NONE_KEY]
        active = active_positions(v, meps_by_id)
        n = [sum(p["position"] == k for p in active) for k in POSITIONS]
        final = is_final(v)
        for key in keys:
            r = rows[key]
            r["votes"] += 1
            r["cz_attendance"][0] += n[0] + n[1] + n[2]
            r["cz_attendance"][1] += len(active)
            if final:
                r["final"] += 1
                r["cz_final"] = [a + b for a, b in zip(r["cz_final"], n)]
                if n[0] + n[1] >= 2:
                    r["cz_united_final"][1] += 1
                    r["cz_united_final"][0] += n[0] == 0 or n[1] == 0
    out = [r for r in rows.values() if r["votes"]]
    return {"categories": out, "votes_total": len(votes),
            "period": {"from": min((v["date"] for v in votes), default=None), "to": max((v["date"] for v in votes), default=None)}}
