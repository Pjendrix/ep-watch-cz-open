"""Kvíz „Evropské frakce“ (K3): otázky z nejspornějších hlasování období, ve kterých se rozešly evropské frakce.

Otázky nevybírá redakce, ale pravidlo (prahy jsou konstanty níže):
  1. závěrečná hlasování (is_final) s výsledkem přijato / zamítnuto; z každé procedury nejnovější takové hlasování,
  2. spor v celém Parlamentu: menšina (pro vs. proti) má aspoň MIN_MINORITY hlasů pro a proti,
  3. frakce se rozešly: z 8 frakcí (bez nezařazených) aspoň MIN_SIDE většinou pro a aspoň MIN_SIDE většinou proti;
     postoj frakce = nejčastější z pro / proti / zdržel se, při shodě dvou možností frakce postoj nemá (null),
  4. zákon (procedura COD, CNS, APP) projde, když se o něm jmenovitě hlasovalo aspoň LAW_MIN_ROLL_CALLS× (boj o text
     v pozměňovacích návrzích), nebo jde o dohodu s Radou a menšina má aspoň LAW_DEAL_MIN_MINORITY; dohody s Radou mívají
     jen 2–4 jmenovitá hlasování, protože se pozměňovací návrhy řeší dřív v jednáních s Radou,
  5. usnesení (ostatní procedury) projde s aspoň RES_MIN_ROLL_CALLS jmenovitými hlasováními a menšinou aspoň RES_MIN_MINORITY,
  6. pořadí podle počtu jmenovitých hlasování k proceduře (při shodě novější), nejdřív zákony, pak usnesení,
  7. z jednoho tématu (první kategorie, categories_for) nejvýš MAX_PER_TOPIC otázky v celém testu; z každoročně se
     opakujících zpráv (stejný název procedury bez letopočtu) jen nejnovější,
  8. delší test: nejvýš LONG_LAWS zákonů, do LONG doplní usnesení; krátký test: prvních SHORT_LAWS zákonů a SHORT_RES
     usnesení z delšího (krátký je jeho podmnožina). Chybí-li zákony, doplní se usneseními; chybí-li i ta, test je kratší
     (prahy se nikdy automaticky nevolní).

Postoje frakcí jsou z group_counts (data/votes, fetch_votes.py): počty [pro, proti, zdržel se, nehlasoval] za každou
frakci, sečtené z HowTheyVote member_votes podle sloupce group_code. Ten je frakce poslance k datu hlasování, ne dnešní:
ověřeno na datech (poslanec 256852 má v hlasováních postupně PFE, od 9. 2. 2026 NI a od 17. 6. 2026 ECR) a součty
group_counts se u každého hlasování shodují s celkovými counts.

Shodu s frakcemi počítá prohlížeč; tady se nic nehodnotí. Výstup: data/quiz_groups.json (build_web.py).
"""

from __future__ import annotations

import re
from collections import Counter

from categories import categories_for
from vote_kinds import classify, is_final

MIN_MINORITY = 0.20
MIN_SIDE = 2
LAW_MIN_ROLL_CALLS = 10
LAW_DEAL_MIN_MINORITY = 0.30
RES_MIN_ROLL_CALLS = 20
RES_MIN_MINORITY = 0.30
MAX_PER_TOPIC = 3
LONG = 25
LONG_LAWS = 18
SHORT = 12
SHORT_LAWS = 9
SHORT_RES = SHORT - SHORT_LAWS
LEGISLATIVE = {"COD", "CNS", "APP"}
GROUPS = ["EPP", "SD", "PFE", "ECR", "RENEW", "GREEN_EFA", "GUE_NGL", "ESN"]  # 8 frakcí; NI jen informativně
INFO_GROUPS = ["NI"]
POS = ["F", "A", "B"]  # pro, proti, zdržel se (pořadí jako v group_counts)
RULE = (
    "Závěrečná hlasování za celé volební období, ve kterých se rozešel Parlament "
    f"(menšina aspoň {round(MIN_MINORITY * 100)} % hlasů pro a proti) i evropské frakce (aspoň {MIN_SIDE} frakce většinou pro "
    f"a aspoň {MIN_SIDE} většinou proti): zákony, o kterých se jmenovitě hlasovalo aspoň {LAW_MIN_ROLL_CALLS}×, nebo dohody s Radou "
    f"s menšinou aspoň {round(LAW_DEAL_MIN_MINORITY * 100)} %, a usnesení s aspoň {RES_MIN_ROLL_CALLS} jmenovitými hlasováními "
    f"a menšinou aspoň {round(RES_MIN_MINORITY * 100)} %, seřazené podle počtu jmenovitých hlasování; "
    f"z jednoho tématu nejvýš {MAX_PER_TOPIC} otázky a z každoročních zpráv jen nejnovější."
)
PARAMS = {
    "MIN_MINORITY": MIN_MINORITY,
    "MIN_SIDE": MIN_SIDE,
    "LAW_MIN_ROLL_CALLS": LAW_MIN_ROLL_CALLS,
    "LAW_DEAL_MIN_MINORITY": LAW_DEAL_MIN_MINORITY,
    "RES_MIN_ROLL_CALLS": RES_MIN_ROLL_CALLS,
    "RES_MIN_MINORITY": RES_MIN_MINORITY,
    "MAX_PER_TOPIC": MAX_PER_TOPIC,
    "LONG": LONG,
    "LONG_LAWS": LONG_LAWS,
    "SHORT": SHORT,
    "SHORT_LAWS": SHORT_LAWS,
    "GROUPS": GROUPS,
}

_YEARS_RE = re.compile(r"\b(19|20)\d{2}\b")


def group_position(row: list[int] | None) -> dict:
    """Postoj frakce z [pro, proti, zdržel se, nehlasoval]: nejčastější z pro / proti / zdržel se; remíza nebo nikdo = null.
    share = podíl většiny z hlasujících (pro + proti + zdržel se)."""
    counts = list(row) if row else [0, 0, 0, 0]
    voting = counts[:3]
    top = max(voting)
    if top == 0 or voting.count(top) > 1:
        return {"pos": None, "share": None, "counts": counts}
    return {"pos": POS[voting.index(top)], "share": round(top / sum(voting), 4), "counts": counts}


def minority(counts: dict) -> float:
    total = counts["for"] + counts["against"]
    return min(counts["for"], counts["against"]) / total if total else 0.0


def _strip_years(title: str) -> str:
    t = _YEARS_RE.sub("", title.lower())
    t = re.sub(r"[‐‑‒–—−-]", "-", t)  # zdroj píše jednou „-“, jindy „–“
    return re.sub(r"\s+", " ", t).strip(" -:,")


def recurring_keys(v: dict) -> set[str]:
    """Názvy procedury bez letopočtů (český z EP i anglický z HowTheyVote). Každoroční zprávy (rozpočet, absolutorium,
    právní stát…) mají aspoň jeden z nich stejný: české názvy rozpočtů se neliší, anglické ano („2025 general budget“ /
    „General budget … 2026“), u zprávy o právním státu je to naopak."""
    titles = [v.get("title_cs"), (v.get("procedure") or {}).get("title")]
    return {k for k in (_strip_years(t) for t in titles if t) if k}


def qualify(v: dict, roll_calls: int) -> dict | None:
    """Kandidát podle pravidel 2–5, nebo None. Hlasování už je závěrečné s výsledkem přijato / zamítnuto (pravidlo 1)."""
    m = minority(v["counts"])
    if m < MIN_MINORITY:
        return None
    pos = [group_position(v["group_counts"].get(g))["pos"] for g in GROUPS]
    if pos.count("F") < MIN_SIDE or pos.count("A") < MIN_SIDE:
        return None
    kind = v.get("vote_kind") or classify(v)[0]
    c = {"vote": v, "ref": v["procedure"]["reference"], "roll_calls": roll_calls, "minority": m, "vote_kind": kind,
         "topic": (categories_for(v) or [""])[0]}  # fmt: skip
    if v["procedure"].get("type") in LEGISLATIVE:
        if roll_calls >= LAW_MIN_ROLL_CALLS or (kind == "provisional_agreement" and m >= LAW_DEAL_MIN_MINORITY):
            return {**c, "kind": "zakon"}
        return None
    if roll_calls >= RES_MIN_ROLL_CALLS and m >= RES_MIN_MINORITY:
        return {**c, "kind": "usneseni"}
    return None


def candidates(votes: list[dict]) -> tuple[list[dict], list[dict]]:
    """(zákony, usnesení) splňující pravidla 1–5 a 7 (opakující se zprávy), seřazené podle pravidla 6.
    Z procedury se bere nejnovější závěrečné hlasování, které pravidly projde (např. u Mercosuru závěrečné hlasování
    z prosince 2025, protože pozdější dohoda s Radou měla menšinu jen 17 %)."""
    roll_calls = Counter((v.get("procedure") or {}).get("reference") for v in votes)
    newest: dict[str, dict] = {}
    for v in votes:
        ref = (v.get("procedure") or {}).get("reference")
        if not ref or not is_final(v) or v.get("result") not in ("ADOPTED", "REJECTED"):
            continue
        if ref in newest and (v["date"], v["id"]) <= (newest[ref]["vote"]["date"], newest[ref]["vote"]["id"]):
            continue
        c = qualify(v, roll_calls[ref])
        if c:
            newest[ref] = c
    laws = [c for c in newest.values() if c["kind"] == "zakon"]
    res = [c for c in newest.values() if c["kind"] == "usneseni"]

    def order(cs: list[dict]) -> list[dict]:
        cs.sort(key=lambda c: (-c["roll_calls"], -int(c["vote"]["date"].replace("-", "")), c["vote"]["id"]))
        return cs

    # z každoročně se opakujících zpráv jen nejnovější (v obou skupinách zvlášť, ale klíč je společný)
    # z každoročně se opakujících zpráv jen nejnovější: zprávy se stejným klíčem (i přes třetí zprávu) tvoří řadu
    series: list[tuple[set[str], list[dict]]] = []
    for c in laws + res:
        keys = recurring_keys(c["vote"])
        hit = [s for s in series if s[0] & keys]
        merged = (keys.union(*(s[0] for s in hit)), [c, *(x for s in hit for x in s[1])])
        series = [s for s in series if not any(s is h for h in hit)] + [merged]
    newest_ids = {max(cs, key=lambda c: (c["vote"]["date"], c["vote"]["id"]))["vote"]["id"] for _, cs in series}
    keep = lambda c: c["vote"]["id"] in newest_ids  # noqa: E731
    return order([c for c in laws if keep(c)]), order([c for c in res if keep(c)])


def pick(laws: list[dict], res: list[dict]) -> tuple[list[dict], list[dict]]:
    """Delší test (pravidla 7–8) a krátký jako jeho podmnožina: (long, short) v pořadí zákony, pak usnesení."""
    per_topic: Counter = Counter()
    long_laws, long_res = [], []
    for c in laws:
        if len(long_laws) == LONG_LAWS:
            break
        if per_topic[c["topic"]] < MAX_PER_TOPIC:
            long_laws.append(c)
            per_topic[c["topic"]] += 1
    for c in res:
        if len(long_laws) + len(long_res) == LONG:
            break
        if per_topic[c["topic"]] < MAX_PER_TOPIC:
            long_res.append(c)
            per_topic[c["topic"]] += 1
    short_laws = long_laws[:SHORT_LAWS]
    short_res = long_res[: SHORT - len(short_laws)]
    return long_laws + long_res, short_laws + short_res


def question(c: dict) -> dict:
    v = c["vote"]
    cnt = v["counts"]
    gc = v["group_counts"]
    return {
        "id": v["id"],
        "date": v["date"],
        "month": v["date"][:7],
        "title": v.get("title_cs") or v.get("title") or v["procedure"].get("title"),
        "title_en": v["procedure"].get("title"),
        "description": v.get("description_cs") or v.get("description"),
        "procedure": c["ref"],
        "proc_type": v["procedure"].get("type"),
        "kind": c["kind"],
        "vote_kind": c["vote_kind"],
        "result": v["result"],
        "topic": c["topic"] or None,
        "roll_calls": c["roll_calls"],
        "minority": round(c["minority"], 4),
        "counts": [cnt["for"], cnt["against"], cnt["abstention"]],
        "groups": {g: group_position(gc.get(g)) for g in GROUPS + [g for g in INFO_GROUPS if g in gc]},
    }


def build_quiz_groups(votes: list[dict]) -> dict:
    for v in votes:
        if "group_counts" not in v or "counts" not in v:
            from compute_stats import FormatError

            raise FormatError(f"hlasování {v.get('id')}: chybí group_counts nebo counts")
    laws, res = candidates(votes)
    long_, short = pick(laws, res)
    return {
        "rule": RULE,
        "params": PARAMS,
        "short": [c["vote"]["id"] for c in short],
        "long": [c["vote"]["id"] for c in long_],
        "questions": [question(c) for c in long_],  # krátký je podmnožina delšího
    }


def main() -> int:
    """Výpis obou výběrů ke kontrole: python scripts/quiz_groups.py"""
    from pathlib import Path

    from compute_stats import load_votes

    _, votes = load_votes(Path(__file__).resolve().parent.parent / "data" / "votes")
    q = build_quiz_groups(votes)
    by_id = {x["id"]: x for x in q["questions"]}
    short = set(q["short"])
    sym = {"F": "+", "A": "−", "B": "0", None: "·"}
    print("Postoje frakcí: " + " ".join(GROUPS) + "  (+ pro, − proti, 0 zdržel, · bez postoje)")
    for n, vid in enumerate(q["long"], 1):
        x = by_id[vid]
        pos = "".join(sym[x["groups"][g]["pos"]] for g in GROUPS)
        print(
            f"{n:2} {'K' if vid in short else ' '} {x['kind']:8} {x['date']} {x['procedure']:16} {x['roll_calls']:4}× "
            f"menš. {x['minority'] * 100:4.1f} % {pos} {x['topic'] or '-':6} {x['result'][:3]} {x['title_en'][:70]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
