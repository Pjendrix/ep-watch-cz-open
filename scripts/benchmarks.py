"""Srovnání s celým EP: mediány účasti na hlasování a hlasování s frakcí přes všechny poslance (R8).

Bez pořadí a žebříčků, jen mediány celého EP a každé frakce. Počítá se ze stejného exportu
HowTheyVote jako české metriky a stejnými pravidly (compute_stats.group_majority, závěrečná hlasování
podle vote_kinds). Rozdíl: u poslanců jiných států nemáme mandáty z EP API, proto se počítají
všechna hlasování, ve kterých je HowTheyVote vede (u Čechů jen hlasování v době mandátu podle EP).
Do mediánu se berou jen poslanci (u frakce poslanec v dané frakci) s aspoň MIN_VOTES hlasováními.

Vstup: řádky (vote_id, member_id, position, group_code) za všechny poslance, group_counts a množina
ID závěrečných hlasování. Výstup: malý slovník pro data/benchmarks.json.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from compute_stats import VOTED, group_majority

MIN_VOTES = 100
METRICS = ["attendance", "attendance_main", "group_loyalty"]

DEFINITION = (
    "Medián EP a medián frakce: prostřední hodnota přes všechny poslance EP (nebo poslance dané frakce), kteří mají "
    f"v datech HowTheyVote aspoň {MIN_VOTES} hlasování. Počítá se stejně jako u českých poslanců (účast na hlasování, "
    "účast u závěrečných hlasování, hlasování s frakcí k datu hlasování), jen u poslanců jiných států se berou "
    "všechna hlasování, ve kterých je HowTheyVote vede. Poslanec s kratším mandátem se srovnává s mediánem počítaným jen z hlasování "
    "v době jeho mandátu. Pořadí poslanců v celém EP záměrně neuvádíme."
)


def _empty() -> dict[str, list[int]]:
    return {m: [0, 0] for m in METRICS}


def window_key(start: str, end: str | None) -> str:
    """Klíč okna mandátu v benchmarks.json: „od_do“ (prázdné do = dosud)."""
    return f"{start}_{end or ''}"


def window_threshold(n_votes: int, min_votes: int = MIN_VOTES) -> int:
    """Kolik hlasování musí poslanec v okně mít, aby šel do mediánu: nejvýš MIN_VOTES, v krátkém okně polovina hlasování okna."""
    return max(1, min(min_votes, -(-n_votes // 2)))


def compute_benchmarks(rows, group_counts: dict[int, dict[str, list[int]]], final_ids: set[int],
                       min_votes: int = MIN_VOTES, windows: dict[str, tuple[str, str | None]] | None = None,
                       vote_dates: dict[int, str] | None = None) -> dict:
    """rows: iterovatelné (vote_id, member_id, position, group_code).

    windows = {klíč: (od, do)} okna mandátu českých poslanců (D7); pro každé se medián EP a frakcí spočítá jen z hlasování
    s datem v okně (vote_dates = {vote_id: datum}), aby poslanec s kratším mandátem nebyl srovnáván s mediánem za celé
    období. Okno se stejným rozsahem jako celé období se nepočítá znovu, použije se hlavní medián.
    """
    windows = windows or {}
    keys = ["", *windows]
    in_window: dict[int, list[str]] = {}
    n_votes = {k: 0 for k in keys}
    if windows:
        for vote_id, date in (vote_dates or {}).items():
            ks = [k for k, (start, end) in windows.items() if start <= date and (end is None or date <= end)]
            in_window[vote_id] = ks
            for k in ks:
                n_votes[k] += 1
    by_member: dict[tuple[str, int], dict] = defaultdict(_empty)
    by_member_group: dict[tuple[str, int, str], dict] = defaultdict(_empty)
    for vote_id, member_id, position, group in rows:
        voted = position in VOTED
        final = vote_id in final_ids
        gm = group_majority(group_counts.get(vote_id, {}), group)
        for k in ("", *in_window.get(vote_id, ())):
            targets = [by_member[(k, member_id)]]
            if group:
                targets.append(by_member_group[(k, member_id, group)])
            for t in targets:
                t["attendance"][0] += voted
                t["attendance"][1] += 1
                if final:
                    t["attendance_main"][0] += voted
                    t["attendance_main"][1] += 1
                if voted and gm is not None:
                    t["group_loyalty"][0] += position == gm
                    t["group_loyalty"][1] += 1

    def medians(items: list[dict], threshold: int) -> dict:
        items = [x for x in items if x["attendance"][1] >= threshold]
        out = {"meps": len(items)}
        for m in METRICS:
            vals = [x[m][0] / x[m][1] for x in items if x[m][1]]
            out[m] = round(median(vals), 4) if vals else None
        return out

    def block(k: str, threshold: int) -> dict:
        groups: dict[str, list[dict]] = defaultdict(list)
        for (kk, _, group), st in by_member_group.items():
            if kk == k:
                groups[group].append(st)
        return {"ep": medians([st for (kk, _), st in by_member.items() if kk == k], threshold),
                "groups": {g: medians(items, threshold) for g, items in sorted(groups.items())}}

    out = {"min_votes": min_votes, "definition": DEFINITION, **block("", min_votes)}
    if windows:
        out["windows"] = {k: {"from": windows[k][0], "to": windows[k][1], "votes": n_votes[k],
                              "min_votes": window_threshold(n_votes[k], min_votes), **block(k, window_threshold(n_votes[k], min_votes))}
                          for k in windows}
    return out
