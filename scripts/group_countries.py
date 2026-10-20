"""Složení politických skupin EP podle zemí k datu posledního hlasování v datech (zadání 20. 10. 2026, F1a).

Zdroj: member_votes z exportu HowTheyVote (stahuje fetch_votes.py, nic dalšího se nestahuje). Pravidlo:
  - vezmou se všechna hlasování posledního plenárního dne v datech (max(date)),
  - pro každého poslance jeho řádek z posledního hlasování toho dne, ve kterém je (frakce a stát k tomu hlasování),
  - poslanci se spočítají podle group_code × country_code. DID_NOT_VOTE se počítá: poslanec je v mandátu.
Kontrola: počet poslanců = součet hlasů (pro, proti, zdržel, nehlasoval) u posledního hlasování dne. Když nesedí,
skript skončí čitelnou chybou. Státy se převedou na ISO alfa-2 podle ručního číselníku data/manual/countries_cs.json;
neznámý stát je chyba (žádné odhady). Nezařazení (NI) nejsou frakce, ale do kontrolního součtu patří.
"""

from __future__ import annotations

from collections import Counter


class CompositionError(ValueError):
    pass


def iso3_to_iso2(countries_doc: dict) -> dict[str, str]:
    """{alfa-3: alfa-2} z data/manual/countries_cs.json."""
    out = {}
    for a2, c in (countries_doc.get("countries") or {}).items():
        if not c.get("iso3") or not c.get("cs"):
            raise CompositionError(f"countries_cs.json: země {a2} nemá iso3 nebo český název")
        out[c["iso3"]] = a2
    return out


def composition(votes: list[dict], rows, iso2: dict[str, str]) -> dict:
    """votes: [{id, timestamp, total}] (total = pro + proti + zdržel + nehlasoval), rows: [(vote_id, member_id, country_code,
    group_code)] pro hlasování posledního dne (jiná se ignorují). Vrací {as_of, vote_id, members, groups: {kód: {seats,
    n_countries, by_country: [{cc, n}]}}}, řazení zemí podle n sestupně, při shodě podle cc."""
    if not votes:
        raise CompositionError("složení frakcí: žádná hlasování")
    day = max(v["timestamp"][:10] for v in votes)
    day_votes = sorted((v for v in votes if v["timestamp"][:10] == day), key=lambda v: (v["timestamp"], int(v["id"])))
    order = {int(v["id"]): i for i, v in enumerate(day_votes)}
    last = day_votes[-1]
    latest: dict[int, tuple[int, str, str]] = {}
    for vid, mid, cc, gc in rows:
        vid, mid = int(vid), int(mid)
        if vid not in order:
            continue
        if not cc or not gc:
            raise CompositionError(f"member_votes: hlasování {vid}, poslanec {mid} nemá stát nebo frakci")
        if mid not in latest or order[vid] > latest[mid][0]:
            latest[mid] = (order[vid], cc, gc)
    total = int(last["total"])
    if len(latest) != total:
        raise CompositionError(
            f"složení frakcí k {day}: {len(latest)} poslanců v member_votes, ale u posledního hlasování {last['id']} je {total} hlasů"
        )
    unknown = sorted({cc for _, cc, _ in latest.values()} - set(iso2))
    if unknown:
        raise CompositionError(f"složení frakcí: stát {unknown} není v data/manual/countries_cs.json")
    counts = Counter((gc, iso2[cc]) for _, cc, gc in latest.values())
    groups: dict[str, dict] = {}
    for (gc, cc), n in counts.items():
        groups.setdefault(gc, {"seats": 0, "by_country": []})
        groups[gc]["seats"] += n
        groups[gc]["by_country"].append({"cc": cc, "n": n})
    for g in groups.values():
        g["by_country"].sort(key=lambda x: (-x["n"], x["cc"]))
        g["n_countries"] = len(g["by_country"])
    if sum(g["seats"] for g in groups.values()) != total:
        raise CompositionError("složení frakcí: součet křesel nesedí s počtem poslanců")
    return {
        "as_of": day,
        "vote_id": int(last["id"]),
        "members": total,
        "groups": {
            k: {"seats": g["seats"], "n_countries": g["n_countries"], "by_country": g["by_country"]} for k, g in sorted(groups.items())
        },
    }
