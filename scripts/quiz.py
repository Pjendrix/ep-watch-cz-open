"""Moje shoda s poslanci (N5): otázky pro kvíz a hlasy českých poslanců v nich.

Otázky nevybírá redakce, ale jedno pravidlo (QUIZ_RULE): závěrečná hlasování o zákonech (COD, CNS, APP) za posledních
12 měsíců (vůči poslednímu hlasování v datech), ve kterých se čeští poslanci nejvíc rozdělili. Z každé procedury jen
nejnovější hlasování, nejvýš QUIZ_SIZE otázek. Rozdělení Čechů je podmínka proto, aby odpovědi poslance od sebe odlišily:
u hlasování, kde všichni hlasovali stejně, by vyšla stejná shoda se všemi.

Shodu počítá prohlížeč (public/moje-shoda.html) z hlasů v tomto souboru; tady se nic nehodnotí ani nepočítá za uživatele.
Hlasy jsou jen poslanců v mandátu k datu hlasování (F pro, A proti, B zdržel/a se, N nehlasoval/a).

Výstup: data/quiz.json (build_web.py).
"""
from __future__ import annotations

import datetime as dt

from compute_stats import active_positions, cz_split
from vote_kinds import classify, is_final

QUIZ_SIZE = 15
LEGISLATIVE = {"COD", "CNS", "APP"}
LETTER = {"FOR": "F", "AGAINST": "A", "ABSTENTION": "B", "DID_NOT_VOTE": "N"}
QUIZ_RULE = (f"Nejvýš {QUIZ_SIZE} závěrečných hlasování o zákonech (řádný postup, konzultace, souhlas) za posledních 12 měsíců, "
             "ve kterých se čeští poslanci nejvíc rozdělili mezi pro a proti; z každého zákona jen nejnovější hlasování.")


def build_quiz(votes: list[dict], meps_by_id: dict) -> dict:
    if not votes:
        return {"rule": QUIZ_RULE, "from": None, "to": None, "questions": []}
    last = max(v["date"] for v in votes)
    since = (dt.date.fromisoformat(last) - dt.timedelta(days=365)).isoformat()
    newest: dict[str, tuple[dict, list[dict], tuple]] = {}
    for v in votes:
        proc = v.get("procedure") or {}
        if (v["date"] < since or not is_final(v) or proc.get("type") not in LEGISLATIVE or not proc.get("reference")
                or v.get("result") not in ("ADOPTED", "REJECTED")):
            continue
        cz = active_positions(v, meps_by_id)
        split = cz_split(cz)
        if not split:
            continue
        ref = proc["reference"]
        if ref not in newest or (v["date"], v["id"]) > (newest[ref][0]["date"], newest[ref][0]["id"]):
            newest[ref] = (v, cz, split)
    # nejvíc rozdělené nahoře; při shodě víc hlasujících Čechů, pak novější
    picked = sorted(newest.values(), key=lambda x: (-x[2][0], -(x[2][1] + x[2][2]), -int(x[0]["date"].replace("-", "")), x[0]["id"]))
    picked = sorted(picked[:QUIZ_SIZE], key=lambda x: (x[0]["date"], x[0]["id"]), reverse=True)
    questions = []
    for v, cz, _split in picked:
        kind = v.get("vote_kind") or classify(v)[0]
        c = v["counts"]
        questions.append({
            "id": v["id"], "date": v["date"], "month": v["date"][:7],
            "title": v.get("title_cs") or v.get("title") or v["procedure"].get("title"),
            "description": v.get("description_cs") or v.get("description"),
            "procedure": v["procedure"]["reference"], "vote_kind": kind, "result": v["result"],
            "counts": [c["for"], c["against"], c["abstention"]],
            "positions": {str(p["member_id"]): LETTER[p["position"]] for p in sorted(cz, key=lambda p: p["member_id"])},
        })
    return {"rule": QUIZ_RULE, "from": since, "to": last, "questions": questions}
