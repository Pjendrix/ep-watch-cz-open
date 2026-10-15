"""Přehled práce českých europoslanců (stránka Práce): souhrny nad data/own_work.json, speeches.json a attendance.json.

Žádné nové zdroje a žádné skóre: jen součty, rozpady a seznamy, které si čtenář může ověřit v tabulce po poslancích a na profilech.
Texty se v součtech počítají jednou, i když na nich pracovali dva Češi (společný zpravodaj, zpravodaj a stínový zpravodaj téhož textu).
Velikost frakce neupravujeme, jen ji ukazujeme (počet poslanců a průměr na poslance), řazení podle počtu poslanců, ne podle výkonu.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from compute_stats import in_mandate

PROCESS_LABEL = {
    "COD": "legislativní, řádný postup", "CNS": "legislativní, konzultace", "APP": "legislativní, souhlas",
    "INI": "z vlastního podnětu", "NLE": "nelegislativní akt", "DEC": "absolutorium", "BUD": "rozpočet", "BUI": "rozpočet",
    "DEA": "akt v přenesené pravomoci", "RSP": "usnesení k tématu",
}
LEAD, SHADOW = "report", "shadow_report"
RECENT = 10


def _unique(items_by_mep: dict[str, list[dict]], types: set[str]) -> dict[str, dict]:
    """Položky daných typů, každá jednou (podle ID); u společného textu se role sloučí."""
    out: dict[str, dict] = {}
    for mep_id, items in items_by_mep.items():
        for it in items:
            if it["type"] in types:
                cur = out.setdefault(it["id"], {**it, "lead": [], "shadow": []})
                (cur["shadow"] if it["type"] in ("shadow_report", "shadow_opinion") else cur["lead"]).append(int(mep_id))
    return out


def build_work_hub(own: dict, meps: list[dict], mep_info: dict[int, dict], speeches: dict | None = None,
                   attendance: dict | None = None) -> dict:
    """mep_info = {id: {"group": {"code", "short_label"} | None}} (skupina k poslednímu dni, ze mep_summary)."""
    items_by_mep = {mid: e.get("items", []) for mid, e in own["meps"].items()}
    reports = _unique(items_by_mep, {LEAD, SHADOW})
    opinions = _unique(items_by_mep, {"opinion", "shadow_opinion"})
    questions = _unique(items_by_mep, {"question"})
    lead_ids = {i for i, r in reports.items() if r["type"] == LEAD or r["lead"]}
    shadow_ids = {i for i, r in reports.items() if r["shadow"]}
    adopted = {i for i, r in reports.items() if r["status"] == "ADOPTED"}
    totals = {
        "meps": len(meps),
        "reports_lead": len(lead_ids), "reports_shadow": len(shadow_ids), "reports_adopted": len(adopted),
        "opinions": len(opinions), "questions": len(questions),
    }
    # projevy a prezence (jen v době mandátu, stejně jako jinde na webu)
    monthly_speeches: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    sp_total = [0, 0.0, 0]
    if speeches:
        for m in meps:
            for r in speeches["meps"].get(str(m["id"]), []):
                if r["type"] == "speech" and in_mandate(m["mandates"], r["date"]):
                    cell = monthly_speeches[r["date"][:7]]
                    cell[0] += 1
                    cell[1] += r.get("minutes") or 0
                    sp_total[0] += 1
                    sp_total[1] += r.get("minutes") or 0
                if r["type"] == "written_statement" and in_mandate(m["mandates"], r["date"]):
                    sp_total[2] += 1
        totals.update({"speeches": sp_total[0], "speeches_minutes": round(sp_total[1]), "written_statements": sp_total[2]})
    if attendance:
        pres = [0, 0]
        for m in meps:
            mine = [d for d in attendance["days"] if in_mandate(m["mandates"], d["date"])]
            pres[0] += sum(m["id"] in d["present"] for d in mine)
            pres[1] += len(mine)
        totals["presence"] = pres
    monthly_questions = Counter(q["date"][:7] for q in questions.values() if q.get("date"))
    months = sorted(set(monthly_speeches) | set(monthly_questions))
    timeline = [{"month": mo, "speeches": int(monthly_speeches[mo][0]) if mo in monthly_speeches else 0,
                 "questions": monthly_questions.get(mo, 0)} for mo in months]
    # podle typu procedury: kolik zpráv (vede / stínové) a kolik z nich přijal Parlament
    by_process: dict[str, dict] = {}
    for i, r in reports.items():
        row = by_process.setdefault(r.get("process_type") or "?", {"process_type": r.get("process_type") or "?", "reports_lead": 0,
                                                                   "reports_shadow": 0, "adopted": 0,
                                                                   "legislative": bool(r.get("legislative"))})
        row["reports_lead"] += i in lead_ids
        row["reports_shadow"] += i in shadow_ids
        row["adopted"] += i in adopted
    for row in by_process.values():
        row["label"] = PROCESS_LABEL.get(row["process_type"], row["process_type"])
    # podle frakcí (frakce poslance k poslednímu dni; velikost se jen ukazuje)
    groups: dict[str, dict] = {}
    for m in meps:
        g = (mep_info.get(m["id"]) or {}).get("group") or {"code": "", "short_label": "bez frakce"}
        row = groups.setdefault(g["code"], {"code": g["code"], "short_label": g["short_label"], "meps": 0, "reports_lead": 0,
                                            "reports_shadow": 0, "opinions": 0, "questions": 0, "speeches": 0})
        row["meps"] += 1
        items = items_by_mep.get(str(m["id"]), [])
        row["reports_lead"] += sum(1 for x in items if x["type"] == LEAD)
        row["reports_shadow"] += sum(1 for x in items if x["type"] == SHADOW)
        row["opinions"] += sum(1 for x in items if x["type"] in ("opinion", "shadow_opinion"))
        row["questions"] += sum(1 for x in items if x["type"] == "question")
        if speeches:
            row["speeches"] += sum(1 for r in speeches["meps"].get(str(m["id"]), [])
                                   if r["type"] == "speech" and in_mandate(m["mandates"], r["date"]))
    # naposledy přijaté zprávy s českou stopou (podle hlasování, jedna řádka na hlasování)
    by_vote: dict[int, dict] = {}
    for i in adopted:
        r = reports[i]
        if not r.get("vote_id"):
            continue
        cur = by_vote.setdefault(r["vote_id"], {"vote_id": r["vote_id"], "date": r.get("vote_date"), "report": r.get("label"),
                                                "title": (r.get("title") or {}).get("cs") or (r.get("title") or {}).get("en"),
                                                "process_type": r.get("process_type"), "legislative": bool(r.get("legislative")),
                                                "lead": [], "shadow": []})
        cur["lead"] = sorted(set(cur["lead"]) | set(r["lead"]))
        cur["shadow"] = sorted(set(cur["shadow"]) | set(r["shadow"]))
    recent = sorted(by_vote.values(), key=lambda x: (x["date"] or "", x["vote_id"]), reverse=True)[:RECENT]
    return {
        "source": own["source"], "updated": own["updated"], "complete": own["complete"],
        "totals": totals, "timeline": timeline,
        "by_process": sorted(by_process.values(), key=lambda r: (-(r["reports_lead"] + r["reports_shadow"]), r["process_type"])),
        "by_group": sorted(groups.values(), key=lambda r: (-r["meps"], r["short_label"])),
        "recent_adopted": recent,
        "adopted_with_vote": len(by_vote),
    }
