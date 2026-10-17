"""Společné části pro detail hlasování, stránky v/ a karty ke sdílení: čeští poslanci podle strany (S2, S5).

Strana a frakce se berou k datu hlasování (cz_positions). Nic se tu nepočítá nově, jen se hlasy skládají do řádků.
"""

from __future__ import annotations

POSITION_LABEL = {"FOR": "pro", "AGAINST": "proti", "ABSTENTION": "zdržel/a se", "DID_NOT_VOTE": "nehlasoval/a"}
POSITIONS = ["FOR", "AGAINST", "ABSTENTION", "DID_NOT_VOTE"]
SHORT_LABEL = {"FOR": "pro", "AGAINST": "proti", "ABSTENTION": "zdrž.", "DID_NOT_VOTE": "nehl."}
MAX_CARD_ROWS = 12


def group_label(code: str | None, groups: list[dict]) -> str:
    if not code:
        return "bez frakce"
    g = next((x for x in groups if x["code"] == code or x.get("ep_code") == code), None)
    if g and g["code"] == "NI":
        return "nezařazení"
    return g["short_label"] if g else code


def by_gender(mep: dict, male: str, female: str) -> str:
    g = mep.get("gender")
    if g == "FEMALE":
        return female
    if g == "MALE":
        return male
    return f"{male}/{female[len(male) :]}" if female.startswith(male) else f"{male} / {female}"


def position_for(position: str, mep: dict) -> str:
    if position == "ABSTENTION":
        return by_gender(mep, "zdržel se", "zdržela se")
    if position == "DID_NOT_VOTE":
        return by_gender(mep, "nehlasoval", "nehlasovala")
    return POSITION_LABEL[position]


def position_phrase(position: str, members: list[dict]) -> str:
    """Slovo hlasu ve správném rodě a čísle: „pro“, „zdržela se“, „zdrželi se“, „nehlasovaly“."""
    if position == "FOR":
        return "pro"
    if position == "AGAINST":
        return "proti"
    if len(members) == 1:
        return position_for(position, members[0])
    fem = all(m.get("gender") == "FEMALE" for m in members)
    if position == "ABSTENTION":
        return "zdržely se" if fem else "zdrželi se"
    return "nehlasovaly" if fem else "nehlasovali"


def party_rows(cz: list[dict], meps_by_id: dict, parties: list[dict], groups: list[dict]) -> list[dict]:
    """Čeští poslanci podle strany k datu hlasování. Strany od největší (podle počtu poslanců v hlasování), pak abecedně.
    Skupina bez strany je „Ind.“ (štítek z parties.json). Frakce k datu hlasování; když se liší, vypíšou se všechny."""
    by_id = {p["id"]: p for p in parties}
    rows: dict[str, dict] = {}
    for p in cz:
        entry = by_id.get(p.get("national_party_id"))
        label = (entry or {}).get("short_label") or (
            p.get("national_party") if p.get("national_party") not in (None, "Independent") else "Ind."
        )
        row = rows.setdefault(
            label, {"label": label, "color": (entry or {}).get("chart_color"), "groups": [], "members": {k: [] for k in POSITIONS}}
        )
        g = group_label(p.get("group_code"), groups)
        if g not in row["groups"]:
            row["groups"].append(g)
        row["members"][p["position"]].append(meps_by_id[p["member_id"]])
    for row in rows.values():
        row["groups"].sort()
        for k in POSITIONS:
            row["members"][k].sort(key=lambda m: m.get("sort_label") or m["name"])
        row["total"] = sum(len(v) for v in row["members"].values())
    return sorted(rows.values(), key=lambda r: (-r["total"], r["label"]))


def card_parties(rows: list[dict], max_rows: int = MAX_CARD_ROWS) -> list[dict]:
    """Řádky stran pro kartu: [{label, groups, positions}]. Když by se nevešly, sloučí se jednočlenné strany do „ostatní“
    (jména stran zůstanou v popisu)."""
    items = [
        {"label": r["label"], "groups": r["groups"], "positions": [k for k in POSITIONS for _ in r["members"][k]], "total": r["total"]}
        for r in rows
    ]
    if len(items) > max_rows:
        keep = [i for i in items if i["total"] > 1]
        rest = [i for i in items if i["total"] == 1]
        while len(keep) >= max_rows and keep:  # ani větší strany se nevejdou: nechat největší
            rest.insert(0, keep.pop())
        keep.append(
            {
                "label": "ostatní",
                "groups": [i["label"] for i in sorted(rest, key=lambda i: i["label"])],
                "positions": sorted((k for i in rest for k in i["positions"]), key=POSITIONS.index),
                "total": sum(i["total"] for i in rest),
            }
        )
        items = keep
    return items
