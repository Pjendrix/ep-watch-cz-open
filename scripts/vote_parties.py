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


def card_items(cz: list[dict], meps_by_id: dict, parties: list[dict], groups: list[dict]) -> list[dict]:
    """Strany pro kartu hlasování se jmény (zadání 20. 10. 2026, K1): strana a frakce k datu hlasování, nezávislí každý
    zvlášť. [{partyId, label, logo, aspect, color, group, groups, independent, members: [{id, surname, sortLabel, position}],
    positions}] od největší strany, při shodě podle názvu; poslanci podle hlasu (pro → proti → zdržel → nehlasoval)
    a uvnitř podle sort_label. Shodná příjmení dostanou iniciálu. Zrcadlo cardItems() v public/lib/ui.js."""
    by_id = {p["id"]: p for p in parties}
    items: dict[str, dict] = {}
    for p in cz:
        m = meps_by_id[p["member_id"]]
        entry = by_id.get(p.get("national_party_id"))
        indep = bool((entry or {}).get("independent")) or not entry and p.get("national_party") in (None, "Independent")
        if indep:
            key = f"ind-{m['id']}"
            label = {"FEMALE": "nezávislá", "MALE": "nezávislý"}.get(m.get("gender"), "nezávislý poslanec")
        else:
            key = str((entry or {}).get("id") or p.get("national_party"))
            label = (entry or {}).get("short_label") or p.get("national_party")
        it = items.setdefault(
            key,
            {
                "partyId": None if indep or not entry else entry["id"],
                "label": label,
                "logo": None if indep else (entry or {}).get("logo"),
                "aspect": None if indep else (entry or {}).get("logo_aspect"),
                "color": None if indep else (entry or {}).get("chart_color") or (entry or {}).get("color"),
                "independent": indep,
                "groups": [],
                "members": [],
            },
        )
        g = group_label(p.get("group_code"), groups)
        if g not in it["groups"]:
            it["groups"].append(g)
        it["members"].append(
            {
                "id": m["id"],
                "surname": m.get("family_name") or m["name"],
                "given": m.get("given_name") or "",
                "sortLabel": m.get("sort_label") or m["name"],
                "position": p["position"],
            }
        )
    surnames = [x["surname"] for it in items.values() for x in it["members"]]
    out = []
    for it in items.values():
        it["groups"].sort()
        it["group"] = " · ".join(it["groups"])
        it["members"].sort(key=lambda x: (POSITIONS.index(x["position"]), x["sortLabel"]))
        for x in it["members"]:
            if surnames.count(x["surname"]) > 1 and x["given"]:
                x["surname"] = f"{x['given'][0]}. {x['surname']}"
            del x["given"]
        it["positions"] = [x["position"] for x in it["members"]]
        out.append(it)
    return sorted(out, key=lambda r: (-len(r["members"]), r["label"].casefold()))


ROLE_CS = {
    "rapporteur": ("zpravodaj", "zpravodajka"),
    "co": ("spoluzpravodaj", "spoluzpravodajka"),
    "shadow": ("stínový zpravodaj", "stínová zpravodajka"),
}


def group_majority(row: list[int]) -> str | None:
    """Většina frakce z [pro, proti, zdržel se, nehlasoval]: jednoznačně nejvíc hlasů pro / proti / zdržel se, jinak None."""
    best = max(row[:3])
    winners = [i for i, n in enumerate(row[:3]) if n == best]
    return POSITIONS[winners[0]] if best > 0 and len(winners) == 1 else None


def vote_detail(
    v: dict,
    cz: list[dict],
    meps_by_id: dict,
    parties: list[dict],
    groups: list[dict],
    roles: list[dict] | None = None,
    summary: dict | None = None,
    procedure: dict | None = None,
) -> dict:
    """Podklady 2. a 3. obrázku detailu karty hlasování (share.js): frakce v celém EP (group_counts), Češi, kteří hlasovali
    jinak než většina jejich frakce (k datu hlasování, nezařazení se nepočítají, nehlasoval se nepočítá jako „jinak“),
    česká stopa, AI shrnutí (jen když existuje, vote_summaries.json) a stav procedury (Příběh zákona). Nic se nedopočítává."""
    by_id = {p["id"]: p for p in parties}
    rows = sorted(v.get("group_counts", {}).items(), key=lambda x: (-sum(x[1]), x[0]))
    out_groups = [
        {
            "code": code,
            "label": group_label(code, groups),
            "counts": row,
            "cz": sum(1 for p in cz if p.get("group_code") == code),
            "majority": group_majority(row),
        }
        for code, row in rows
        if code != "NI"
    ]
    diverged = []
    for p in cz:
        code, row = p.get("group_code"), v.get("group_counts", {}).get(p.get("group_code") or "")
        if not row or code == "NI" or p["position"] == "DID_NOT_VOTE":
            continue
        maj = group_majority(row)
        if maj and p["position"] != maj:
            m = meps_by_id[p["member_id"]]
            party = by_id.get(p.get("national_party_id"))
            diverged.append(
                {
                    "name": f"{m.get('given_name') or ''} {m.get('family_name') or m['name']}".strip(),
                    "party": None if not party or party.get("independent") else party["short_label"],
                    "group": group_label(code, groups),
                    "position": p["position"],
                    "majority": maj,
                    "sortLabel": m.get("sort_label") or m["name"],
                }
            )
    diverged.sort(key=lambda x: x["sortLabel"])
    trace = []
    for r in roles or []:
        m = meps_by_id.get(r["mep_id"])
        if not m or r["role"] not in ROLE_CS or any(t["id"] == m["id"] for t in trace):
            continue
        male, female = ROLE_CS[r["role"]]
        trace.append(
            {
                "id": m["id"],
                "name": f"{m.get('given_name') or ''} {m.get('family_name') or m['name']}".strip(),
                "role": female if m.get("gender") == "FEMALE" else male if m.get("gender") == "MALE" else f"{male}/ka",
            }
        )
    return {
        "groups": out_groups,
        "diverged": [{k: x[k] for k in ("name", "party", "group", "position", "majority")} for x in diverged],
        "trace": [{k: x[k] for k in ("name", "role")} for x in trace],
        "summary": {"text": summary["shrnuti"], "source": summary.get("source")} if summary and summary.get("shrnuti") else None,
        "procedure": procedure,
    }
