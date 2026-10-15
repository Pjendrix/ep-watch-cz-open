"""Klíčová hlasování (D13): čtyři oddělené seznamy místo jednoho žebříčku, každý s jedním pravidlem a celý z dat.

  1. Zákony, o kterých se rozhodlo: závěrečné hlasování nebo prozatímní dohoda v legislativní proceduře (COD, CNS, APP).
  2. Kde se Češi nejvíc rozdělili: závěrečná hlasování s největším rozdělením českých poslanců (menšina mezi pro a proti).
  3. Nejtěsnější výsledky: závěrečná hlasování s nejmenším rozdílem hlasů pro a proti v celém parlamentu.
  4. Kde Češi hlasovali opačně než parlament: většina českých hlasů pro/proti šla proti výsledku.

Nic se nevybírá ručně a žádný zdroj mimo hlasování (žádná média, žádný scraping). Každý seznam je pro období
poslední zasedání / 3 měsíce / 12 měsíců / celé období, nejvýš 5 položek a celkový počet. U každé položky je věta, proč je
v seznamu, takže je vidět, že výběr nedělá web. Hlavní body zasedání podle tiskových zpráv EP se záměrně nepoužívají:
nemají strojově čitelný zdroj a vyžadovaly by ruční doplňování.

Výstup: data/key_votes.json (build_web.py). Čísla jen z dat hlasování.
"""

from __future__ import annotations

import datetime as dt

from compute_stats import active_positions, cz_split, last_session_dates
from categories import categories_for
from vote_kinds import classify, is_final

LIMIT = 5
LEGISLATIVE = {"COD", "CNS", "APP"}
PERIODS = ["session", "m3", "m12", "all"]
PERIOD_LABEL = {"session": "poslední zasedání", "m3": "3 měsíce", "m12": "12 měsíců", "all": "celé období"}


def period_starts(votes: list[dict]) -> dict[str, str | None]:
    """Počátek každého období vůči poslednímu hlasování v datech (reprodukovatelné, nezávislé na dnešku)."""
    dates = [v["date"] for v in votes]
    if not dates:
        return {p: None for p in PERIODS}
    last = dt.date.fromisoformat(max(dates))
    return {
        "session": min(last_session_dates(dates)),
        "m3": (last - dt.timedelta(days=92)).isoformat(),
        "m12": (last - dt.timedelta(days=365)).isoformat(),
        "all": None,
    }


def _compact(v: dict, meps_by_id: dict) -> dict:
    kind, _inverted = (v["vote_kind"], v.get("inverted", False)) if v.get("vote_kind") else classify(v)
    cz = active_positions(v, meps_by_id)
    c = v["counts"]
    return {"id": v["id"], "date": v["date"], "month": v["date"][:7],
            "title": v.get("title") or (v.get("procedure") or {}).get("title") or v.get("reference"),
            "vote_kind": kind, "result": v.get("result"),
            "counts": {"for": c["for"], "against": c["against"], "abstention": c["abstention"]},
            "cz": [sum(p["position"] == k for p in cz) for k in ("FOR", "AGAINST", "ABSTENTION", "DID_NOT_VOTE")],
            "cats": categories_for(v)}


def _gap_text(gap: int) -> str:
    return f"{gap} " + ("hlas" if gap == 1 else "hlasy" if 2 <= gap <= 4 else "hlasů")


def build_key_votes(votes: list[dict], meps_by_id: dict) -> dict:
    starts = period_starts(votes)
    finals = [v for v in votes if is_final(v)]
    laws = [v for v in finals if (v.get("procedure") or {}).get("type") in LEGISLATIVE]
    splits = []
    against_result = []
    for v in finals:
        cz = active_positions(v, meps_by_id)
        sp = cz_split(cz)
        if sp:
            splits.append((v, sp))
        n_for = sum(p["position"] == "FOR" for p in cz)
        n_against = sum(p["position"] == "AGAINST" for p in cz)
        if v.get("result") in ("ADOPTED", "REJECTED") and n_for != n_against and (n_for > n_against) != (v["result"] == "ADOPTED"):
            against_result.append((v, n_for, n_against))
    close = [v for v in finals if v.get("result") in ("ADOPTED", "REJECTED")]
    gap = lambda v: abs(v["counts"]["for"] - v["counts"]["against"])
    inside = lambda v, p: starts[p] is None or v["date"] >= starts[p]
    out_votes: dict[str, dict] = {}
    lists: dict[str, dict] = {}
    for p in PERIODS:
        lw = sorted((v for v in laws if inside(v, p)), key=lambda v: (v["date"], v["id"]), reverse=True)
        sp = sorted(((v, s) for v, s in splits if inside(v, p)), key=lambda x: (-x[1][0], -(x[1][1] + x[1][2]), x[0]["date"], x[0]["id"]))
        cl = sorted((v for v in close if inside(v, p)), key=lambda v: (gap(v), v["date"], v["id"]))
        ar = sorted(((v, f, a) for v, f, a in against_result if inside(v, p)), key=lambda x: (-max(x[1], x[2]), x[0]["date"], x[0]["id"]))
        chosen = {
            "laws": (len(lw), [(v, f"Závěrečné hlasování v legislativní proceduře {(v.get('procedure') or {}).get('reference') or ''}".strip()) for v in lw[:LIMIT]]),
            "splits": (len(sp), [(v, f"Češi se rozdělili {s[1]} : {s[2]} (pro : proti)") for v, s in sp[:LIMIT]]),
            "close": (len(cl), [(v, f"Výsledek {v['counts']['for']} : {v['counts']['against']}, rozdíl {_gap_text(gap(v))}") for v in cl[:LIMIT]]),
            "against_result": (len(ar), [(v, f"Češi {f} pro : {a} proti, parlament ale text {'přijal' if v['result'] == 'ADOPTED' else 'zamítl'}")
                                         for v, f, a in ar[:LIMIT]]),
        }
        lists[p] = {name: {"total": total, "items": [{"id": v["id"], "reason": reason} for v, reason in picked]}
                    for name, (total, picked) in chosen.items()}
        for _, picked in chosen.values():
            for v, _reason in picked:
                out_votes.setdefault(str(v["id"]), _compact(v, meps_by_id))
    return {
        "periods": {p: {"label": PERIOD_LABEL[p], "from": starts[p]} for p in PERIODS},
        "lists": lists, "votes": out_votes,
        "rules": {
            "laws": "Závěrečné hlasování nebo prozatímní dohoda v legislativní proceduře (COD, CNS, APP), od nejnovějších.",
            "splits": "Závěrečná hlasování, ve kterých se čeští poslanci nejvíc rozdělili (menšina mezi hlasy pro a proti).",
            "close": "Závěrečná hlasování s nejmenším rozdílem hlasů pro a proti v celém parlamentu.",
            "against_result": "Závěrečná hlasování, ve kterých většina českých hlasů pro a proti šla proti výsledku.",
        },
        "note": "Klíčová hlasování nevybíráme ručně: každý seznam má jedno pravidlo, které se dá napsat do jedné věty, a čísla jsou z dat hlasování.",
    }
