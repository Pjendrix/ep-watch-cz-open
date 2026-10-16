"""Program příštího zasedání pro web (blok „Další zasedání“): spojení data/agenda.json (fetch_agenda.py) s českou stopou
z data/own_work.json. Nic se nepočítá nově, jen se páruje číslo zprávy.

Česká stopa u bodu programu = český poslanec je zpravodajem / spoluzpravodajem (položka own_work s id zprávy A-10-RRRR-NNNN)
nebo stínovým zpravodajem (pole report A10-NNNN/RRRR) zprávy, ke které se bod váže. Stanoviska výborů v programu
odkaz na zprávu nemají, proto se nepárují.

Výběr na úvod (pravidlo, ne redakce, rozhodnutí autora 16. 10. 2026): body s dokumentem, nejdřív s českou stopou,
pak s legislativním návrhem (dokument C), pak podle pořadí v programu; nejvýš 3.
"""

from __future__ import annotations

import re

PICKS = 3
ROLE_CS = {"rapporteur": "zpravodaj/ka", "co": "spoluzpravodaj/ka", "shadow": "stínový/á zpravodaj/ka"}


def doc_key(ref: str | None) -> str | None:
    """Jednotný tvar čísla zprávy: „A10-0120/2025“ i „A-10-2025-0120“ → „A-10-2025-0120“."""
    if not ref:
        return None
    m = re.fullmatch(r"([A-Z])-(\d{2})-(\d{4})-(\d{4})", ref)
    if m:
        return ref
    m = re.fullmatch(r"([A-Z])(\d{2})-(\d{4})/(\d{4})", ref)
    return f"{m[1]}-{m[2]}-{m[4]}-{m[3]}" if m else None


def cz_roles_by_doc(own_work: dict | None) -> dict[str, list[dict]]:
    """{číslo zprávy: [{mep_id, role}]} z own_work.json (zpravodaj, spoluzpravodaj, stínový zpravodaj)."""
    out: dict[str, list[dict]] = {}
    for mep_id, entry in ((own_work or {}).get("meps") or {}).items():
        for it in entry.get("items", []):
            if it.get("type") == "report":
                key, role = doc_key(it.get("id")), "co" if it.get("role") == "RAPPORTEUR_CO" else "rapporteur"
            elif it.get("type") == "shadow_report":
                key, role = doc_key(it.get("report")), "shadow"
            else:
                continue
            if key:
                row = {"mep_id": int(mep_id), "role": role}
                if row not in out.setdefault(key, []):
                    out[key].append(row)
    for rows in out.values():
        rows.sort(key=lambda r: (r["role"] == "shadow", r["mep_id"]))
    return out


def agenda_view(agenda: dict | None, own_work: dict | None, names: dict[int, str]) -> dict | None:
    """Program nejbližšího zasedání s českou stopou u bodů a výběrem na úvod. None, když program chybí."""
    nxt = (agenda or {}).get("next")
    if not nxt:
        return None
    roles = cz_roles_by_doc(own_work)
    items = []
    for it in nxt["items"]:
        cz = [{"mep_id": r["mep_id"], "name": names.get(r["mep_id"]), "role": r["role"]}
              for d in it["docs"] for r in roles.get(d, [])]
        items.append({**it, "cz": cz})
    candidates = [x for x in items if x["docs"]]
    picks = sorted(candidates, key=lambda x: (not x["cz"], not x["legislative"], x["date"],
                                              x["order"] if x["order"] is not None else 1e9))[:PICKS]
    return {"from": nxt["from"], "to": nxt["to"], "days": nxt["days"], "votes": len(items), "items": items,
            "picks": [x["id"] for x in picks], "fetched": (agenda or {}).get("fetched"),
            "source": (agenda or {}).get("source")}
