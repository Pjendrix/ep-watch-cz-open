"""Moje shoda s poslanci (N5): otázky pro kvíz a hlasy českých poslanců v nich.

Otázky nevybírá redakce, ale pravidlo (QUIZ_RULE):
  1. závěrečná hlasování o zákonech (COD, CNS, APP) za celé období, přijatá nebo zamítnutá,
  2. jen ta, kde Češi nehlasovali jednotně (aspoň jeden pro a aspoň jeden proti), jinak by otázka poslance neodlišila;
     z každého zákona nejnovější takové hlasování,
  3. pořadí podle počtu jmenovitých hlasování k zákonu v plénu: hodně hlasování = hodně pozměňovacích návrhů = spor,
     tedy zákon, o kterém se diskutovalo (při shodě novější),
  4. z jednoho tématu nejvýš MAX_PER_TOPIC zákonů,
  5. nejvýš polovina otázek smí být „skoro jednomyslná“ (menšina Čechů nejvýš LOPSIDED hlasy), aby test nebyl jen z hlasování
     typu 18 : 1; taková hlasování se ale nevyřazují (i to, že proti hlasovali jen dva poslanci, je informace).
Krátký test má QUIZ_SHORT otázek, dlouhý QUIZ_LONG; oba se vybírají stejným pravidlem.

Shodu počítá prohlížeč (public/moje-shoda.html) z hlasů v tomto souboru; tady se nic nehodnotí ani nepočítá za uživatele.
Hlasy jsou jen poslanců v mandátu k datu hlasování (F pro, A proti, B zdržel/a se, N nehlasoval/a).

Výstup: data/quiz.json (build_web.py). Srozumitelné shrnutí otázek doplňuje zvlášť quiz_summaries.py (Claude Haiku).
"""
from __future__ import annotations

from collections import Counter

from categories import categories_for
from compute_stats import active_positions, cz_split
from vote_kinds import classify, is_final

QUIZ_SHORT = 12
QUIZ_LONG = 25
MAX_PER_TOPIC = 3
LOPSIDED = 2  # menšina Čechů (pro vs. proti) nejvýš tolik hlasů = skoro jednomyslné
LEGISLATIVE = {"COD", "CNS", "APP"}
LETTER = {"FOR": "F", "AGAINST": "A", "ABSTENTION": "B", "DID_NOT_VOTE": "N"}
QUIZ_RULE = ("Závěrečná hlasování o zákonech za celé volební období, ve kterých čeští poslanci nehlasovali jednotně, "
             "seřazená podle toho, kolikrát se o zákonu v plénu jmenovitě hlasovalo (víc hlasování znamená víc sporů o text). "
             f"Z jednoho tématu nejvýš {MAX_PER_TOPIC} zákony a nejvýš polovina otázek s menšinou Čechů do {LOPSIDED} hlasů.")


def pick(candidates: list[dict], size: int) -> list[dict]:
    """Postupně podle pořadí: téma nejvýš MAX_PER_TOPIC×, skoro jednomyslné nejvýš polovina z `size`."""
    out, per_topic, lopsided = [], Counter(), 0
    for c in candidates:
        if len(out) == size:
            break
        if per_topic[c["topic"]] >= MAX_PER_TOPIC or (c["lopsided"] and lopsided >= size // 2):
            continue
        out.append(c)
        per_topic[c["topic"]] += 1
        lopsided += c["lopsided"]
    return out


def build_quiz(votes: list[dict], meps_by_id: dict) -> dict:
    roll_calls = Counter((v.get("procedure") or {}).get("reference") for v in votes)
    newest: dict[str, dict] = {}
    for v in votes:
        proc = v.get("procedure") or {}
        if (not is_final(v) or proc.get("type") not in LEGISLATIVE or not proc.get("reference")
                or v.get("result") not in ("ADOPTED", "REJECTED")):
            continue
        cz = active_positions(v, meps_by_id)
        split = cz_split(cz)
        if not split:
            continue
        ref = proc["reference"]
        if ref not in newest or (v["date"], v["id"]) > (newest[ref]["vote"]["date"], newest[ref]["vote"]["id"]):
            newest[ref] = {"vote": v, "cz": cz, "ref": ref, "roll_calls": roll_calls[ref],
                           "topic": (categories_for(v) or [""])[0], "lopsided": min(split[1], split[2]) <= LOPSIDED}
    candidates = list(newest.values())
    candidates.sort(key=lambda c: (-c["roll_calls"], -int(c["vote"]["date"].replace("-", "")), c["vote"]["id"]))
    long_ = pick(candidates, QUIZ_LONG)
    short = pick(candidates, QUIZ_SHORT)
    questions = []
    for c in sorted({id(c): c for c in long_ + short}.values(), key=lambda c: candidates.index(c)):
        v = c["vote"]
        kind = v.get("vote_kind") or classify(v)[0]
        cnt = v["counts"]
        questions.append({
            "id": v["id"], "date": v["date"], "month": v["date"][:7],
            "title": v.get("title_cs") or v.get("title") or v["procedure"].get("title"),
            "title_en": v["procedure"].get("title"),
            "description": v.get("description_cs") or v.get("description"),
            "procedure": c["ref"], "vote_kind": kind, "result": v["result"], "topic": c["topic"] or None,
            "roll_calls": c["roll_calls"], "counts": [cnt["for"], cnt["against"], cnt["abstention"]],
            "positions": {str(p["member_id"]): LETTER[p["position"]] for p in sorted(c["cz"], key=lambda p: p["member_id"])},
        })
    return {"rule": QUIZ_RULE, "sizes": {"short": QUIZ_SHORT, "long": QUIZ_LONG},
            "short": [c["vote"]["id"] for c in short], "long": [c["vote"]["id"] for c in long_], "questions": questions}
