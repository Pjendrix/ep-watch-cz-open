"""Srovnání s delegacemi podobné velikosti (D5, D6).

Stejná čísla, která web ukazuje o české delegaci (jednotnost, hlasování rozhodnutá hlasy delegace), spočítaná
stejnými pravidly pro delegace ostatních států s 20–22 poslanci. Slouží jako srovnávací základna: bez ní by
„Češi jednotně v 7,7 %“ a „české hlasy rozhodly v N hlasováních“ vyznívaly, jako by šlo o něco, co je pro
Česko zvláštní. Kontrafakt „bez hlasů delegace by hlasování dopadlo opačně“ platí pro jakoukoli skupinu poslanců,
jejíž čistý rozdíl pro/proti převýší celkový rozdíl.

Vstup: počty hlasů po státech (vote_id → stát → [pro, proti, zdržel se, nehlasoval]) z member_votes
HowTheyVote a metadata hlasování. Žádné ruční hodnoty. Výstup: malý slovník pro data/delegations.json.
Poslanci jiných států nemají mandáty z EP API, počítají se proto všichni, které HowTheyVote u hlasování vede
(u Čechů web počítá jen poslance v mandátu; viz metodika).
"""

from __future__ import annotations

from compute_stats import CLOSE_MARGIN, simple_result

MIN_SEATS, MAX_SEATS = 20, 22  # „podobná velikost“: 20–22 poslanců (ČR má 21)
FOR, AGAINST = 0, 1


def delegation_metrics(country_counts: dict[int, dict[str, list[int]]], votes: list[dict], country: str) -> dict:
    """votes: [{id, counts: {for, against, ...}, result, is_final}]. Vrací jednotnost a rozhodující hlasování státu."""
    united = [0, 0]  # [jednotně, posuzovaná hlasování] (aspoň 2 hlasující pro/proti)
    united_final = [0, 0]
    decisive = {"all": 0, "final": 0}
    close = {"all": 0, "final": 0}
    for v in votes:
        row = country_counts.get(v["id"], {}).get(country)
        if row is None:
            continue
        n_for, n_against = row[FOR], row[AGAINST]
        if n_for + n_against >= 2:
            is_united = n_for == 0 or n_against == 0
            united[1] += 1
            united[0] += is_united
            if v["is_final"]:
                united_final[1] += 1
                united_final[0] += is_united
        c = v["counts"]
        if v["result"] in ("ADOPTED", "REJECTED") and abs(c["for"] - c["against"]) <= CLOSE_MARGIN:
            close["all"] += 1
            close["final"] += v["is_final"]
            # stejné pravidlo jako compute_stats.decisive_alternative: jen výsledek odpovídající prosté většině
            if simple_result(c["for"], c["against"]) == v["result"] and \
                    simple_result(c["for"] - n_for, c["against"] - n_against) != v["result"]:
                decisive["all"] += 1
                decisive["final"] += v["is_final"]
    return {"unity": united, "unity_final": united_final, "decisive": decisive, "close": close}


def seats(country_counts: dict[int, dict[str, list[int]]], votes: list[dict]) -> dict[str, int]:
    """Počet poslanců delegace = kolik jich HowTheyVote vede u posledního hlasování v datech."""
    last = max(votes, key=lambda v: (v["date"], v["id"]))["id"]
    return {c: sum(row) for c, row in country_counts.get(last, {}).items()}


def compute_delegations(country_counts, votes: list[dict], own: str = "CZE",
                        min_seats: int = MIN_SEATS, max_seats: int = MAX_SEATS) -> dict:
    n = seats(country_counts, votes)
    if own not in n:
        raise ValueError(f"stát {own} není u posledního hlasování")
    peers = sorted(c for c, s in n.items() if min_seats <= s <= max_seats and c != own)
    countries = {c: {"seats": n[c], **delegation_metrics(country_counts, votes, c)} for c in [own] + peers}

    def span(get) -> dict:
        vals = [get(countries[c]) for c in peers]
        return {"min": min(vals), "max": max(vals)} if vals else {"min": None, "max": None}

    share = lambda pair: (pair[0] / pair[1]) if pair[1] else 0.0
    return {
        "own": own, "peers": peers, "seats_range": [min_seats, max_seats], "countries": countries,
        "peer_range": {
            "unity": span(lambda m: round(share(m["unity"]), 4)),
            "unity_final": span(lambda m: round(share(m["unity_final"]), 4)),
            "decisive": span(lambda m: m["decisive"]["all"]),
            "decisive_final": span(lambda m: m["decisive"]["final"]),
        },
        "definition": (
            f"Delegace s {min_seats}–{max_seats} poslanci (podle počtu poslanců u posledního hlasování v datech). "
            "Jednotnost: podíl hlasování, ve kterých všichni poslanci státu, kteří hlasovali pro nebo proti, byli na jedné "
            "straně (aspoň dva hlasující). Rozhodující: těsné hlasování (rozdíl pro/proti nejvýš "
            f"{CLOSE_MARGIN}), které by bez hlasů pro a proti poslanců státu dopadlo opačně; jen hlasování, jejichž oficiální "
            "výsledek odpovídá prosté většině. U všech států se berou poslanci, které HowTheyVote u hlasování vede."),
    }
