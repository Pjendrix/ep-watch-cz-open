"""Předpočítá odlehčené soubory pro web z data/meps.json, data/stats.json a data/votes/*.json.

Výstup:
  data/overview.json        souhrn pro úvodní tabulku (poslanci + hlavní metriky)
  data/meps/{id}.json       vše pro profil poslance
  data/meps/{id}_votes.json hlasy poslance u všech hlasování v mandátu (filtr „Poslanec“ v seznamu hlasování)
  data/votes/search.json    odlehčený seznam všech hlasování pro seznam a vyhledávání
  data/decisive.json        těsná a rozhodující hlasování
  data/splits.json          kde se Češi rozdělili (poslední zasedání, celé období)
  data/parties/index.json   přehled stran
  data/parties/{id}.json    stránka strany
  data/session.json         shrnutí posledního zasedání pro úvodní stránku
  data/agreement.json       matice shody mezi českými poslanci
  data/work.json            vlastní práce: co prošlo, po poslancích (žebříček v české delegaci)

Nic nepočítá znovu: metriky bere ze stats.json, hlasování z měsíčních souborů.
Měsíční soubory zůstávají pro detail hlasování.

Použití:
    python scripts/build_web.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from compute_stats import (CLOSE_MARGIN, POSITIONS, FormatError, active_positions, in_mandate, load_votes,
                           require, topic_codes)
from activity import count_activity
from attendance import count_presence
from category_stats import category_stats
from group_stats import build_group_stats
from categories import CATEGORIES, categories_for, icon_inner
from key_votes import build_key_votes
from work_hub import build_work_hub
from labels_cs import translate
from overrides import apply_name_overrides
from vote_kinds import KIND_LABELS, classify, is_final

RECENT_MAIN = 15
LAST_SESSION_LIMIT = 50
SHORT_MANDATE_DAYS = 60
# Nová pole jsou na konci, aby starší web četl řádky beze změny. is_final a inverted web odvodí z vote_kind.
SEARCH_FIELDS = ["id", "date", "month", "title", "reference", "description", "amendment_number",
                 "result", "is_main", "cz", "vote_kind", "description_cs", "topics", "cats"]


def current(items: list[dict], day: str) -> dict | None:
    """Členství platné k danému dni, jinak poslední známé."""
    if not items:
        return None
    for x in items:
        if x["start"] <= day and (x["end"] is None or day <= x["end"]):
            return x
    return items[-1]


def vote_title(v: dict) -> str:
    return v.get("title") or (v.get("procedure") or {}).get("title") or v.get("reference") or f"Hlasování {v['id']}"


def kind_fields(v: dict) -> dict:
    """Typ hlasování a český popis; starší měsíční soubory pole nemají, dopočítají se stejnými pravidly."""
    kind, inverted = (v["vote_kind"], v.get("inverted", False)) if v.get("vote_kind") else classify(v)
    desc_cs = v["description_cs"] if "description_cs" in v else translate(v.get("description"))
    return {"vote_kind": kind, "is_final": is_final(v), "inverted": inverted, "description_cs": desc_cs}


def cz_counts(vote: dict, meps_by_id: dict) -> list[int]:
    """Počty [pro, proti, zdržel, nehlasoval] českých poslanců v mandátu."""
    counts = [0, 0, 0, 0]
    for p in vote["cz_positions"]:
        m = meps_by_id.get(p["member_id"])
        if m and in_mandate(m["mandates"], vote["date"]):
            counts[POSITIONS.index(p["position"])] += 1
    return counts


def load_topic_labels(path: Path) -> dict:
    """Ruční český překlad názvů témat OEIL; když soubor chybí, prázdný slovník."""
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    require(doc, ["labels"], path.name)
    return doc["labels"]


def build_search(votes: list[dict], meps_by_id: dict, topic_labels: dict | None = None,
                 oeil: dict | None = None) -> dict:
    topic_labels, oeil = topic_labels or {}, oeil or {}
    rows, used = [], set()
    for v in votes:
        k = kind_fields(v)
        rows.append([v["id"], v["date"], v["date"][:7], vote_title(v), v.get("reference"), v.get("description"),
                     v.get("amendment_number"), v.get("result"), v["is_main"], cz_counts(v, meps_by_id),
                     k["vote_kind"], k["description_cs"], sorted(topic_codes(v)), categories_for(v)])
        used |= topic_codes(v)
    labels = {c: topic_labels.get(c) or oeil.get(c) for c in sorted(used)}
    return {"fields": SEARCH_FIELDS, "positions_order": POSITIONS, "kind_labels": KIND_LABELS,
            "topic_labels": labels, "rows": rows}


def mandate_days(mandates: list[dict], day: str) -> int:
    """Součet dní mandátu (včetně krajních), otevřený mandát do daného dne."""
    import datetime as dt
    total = 0
    for x in mandates:
        start = dt.date.fromisoformat(x["start"])
        end = dt.date.fromisoformat(min(x["end"] or day, day))
        total += max((end - start).days + 1, 0)
    return total


def mep_summary(m: dict, day: str) -> dict:
    g, p = current(m["groups"], day), current(m["parties"], day)
    return {
        "id": m["id"], "name": m["name"], "given_name": m.get("given_name"), "family_name": m.get("family_name"),
        "sort_label": m.get("sort_label"), "gender": m.get("gender"), "photo_url": m.get("photo_url"),
        "mandates": m["mandates"],
        "short_mandate": mandate_days(m["mandates"], day) < SHORT_MANDATE_DAYS,
        "group": {"code": g["code"], "short_label": g["short_label"]} if g else None,
        "party": {"id": int(p["org_id"]), "short_label": p["short_label"]} if p else None,
    }


def build_overview(meps: list[dict], stats: dict, day: str, topic_labels: dict | None = None,
                   bench: dict | None = None) -> dict:
    return {
        "sources": stats["sources"], "period": stats["period"], "votes_total": stats["votes_total"],
        "topics": [{**t, "label_cs": (topic_labels or {}).get(t["code"])} for t in stats.get("topics", [])],
        "definitions": stats["definitions"], "short_mandate_days": SHORT_MANDATE_DAYS,
        "meps": [{**mep_summary(m, day), "total": stats["meps"][str(m["id"])]["total"],
                  "bench_key": bench_key(m) if bench_window(m, bench) else None} for m in meps],
    }


def recent_main_votes(mep: dict, votes: list[dict], limit: int = RECENT_MAIN) -> list[dict]:
    out = []
    for v in reversed(votes):
        if not is_final(v) or not in_mandate(mep["mandates"], v["date"]):
            continue
        pos = next((p for p in v["cz_positions"] if p["member_id"] == mep["id"]), None)
        if pos is None:
            continue
        out.append({"id": v["id"], "date": v["date"], "month": v["date"][:7], "title": vote_title(v),
                    "reference": v.get("reference"), "description": v.get("description"),
                    "result": v.get("result"), "position": pos["position"], "group_code": pos["group_code"],
                    **kind_fields(v)})
        if len(out) >= limit:
            break
    return out


def vote_summary(v: dict, meps_by_id: dict) -> dict:
    """Krátký popis hlasování pro seznamy na webu."""
    return {"id": v["id"], "date": v["date"], "month": v["date"][:7], "title": vote_title(v),
            "reference": v.get("reference"), "description": v.get("description"), "result": v.get("result"),
            "is_main": v["is_main"], "counts": v["counts"], "cz": cz_counts(v, meps_by_id),
            "amendment_number": v.get("amendment_number"), "texts_adopted_reference": v.get("texts_adopted_reference"),
            "cats": categories_for(v), **kind_fields(v)}


def cz_positions(v: dict, meps_by_id: dict) -> list[dict]:
    return [{"member_id": p["member_id"], "position": p["position"], "group_code": p["group_code"],
             "national_party_id": p.get("national_party_id")} for p in active_positions(v, meps_by_id)]


def topic_rows(topics_stats: dict, topics_meta: list[dict], topic_labels: dict | None = None) -> list[dict]:
    return [{"code": t["code"], "label": t["label"], "label_cs": (topic_labels or {}).get(t["code"]),
             **topics_stats[t["code"]]}
            for t in topics_meta if t["code"] in topics_stats]


def last_group_code(mep: dict, votes: list[dict]) -> str | None:
    """Kód frakce (HowTheyVote) v posledním hlasování poslance."""
    for v in reversed(votes):
        for p in v["cz_positions"]:
            if p["member_id"] == mep["id"]:
                return p["group_code"]
    return None


def mep_benchmarks(mep: dict, votes: list[dict], bench: dict | None) -> dict | None:
    """Mediány EP a frakce poslance (data/benchmarks.json z fetch_votes.py); bez pořadí."""
    if not bench:
        return None
    code = last_group_code(mep, votes)
    w = bench_window(mep, bench)
    src = w or bench  # poslanec s kratším mandátem: mediány jen z hlasování v době jeho mandátu (D7)
    return {"source": bench.get("source"), "definition": bench.get("definition"), "min_votes": src.get("min_votes"),
            "ep": src["ep"], "group_code": code, "group": src["groups"].get(code) if code else None,
            "window": {"from": w["from"], "to": w["to"], "votes": w["votes"]} if w else None}


def bench_key(mep: dict) -> str:
    """Klíč okna mandátu poslance v benchmarks.json (od prvního začátku do posledního konce mandátu)."""
    ends = [x["end"] for x in mep["mandates"]]
    return f"{min(x['start'] for x in mep['mandates'])}_{'' if None in ends else max(ends)}"


def bench_window(mep: dict, bench: dict | None) -> dict | None:
    return ((bench or {}).get("windows") or {}).get(bench_key(mep))


def build_profile(mep: dict, meps: list[dict], stats: dict, votes: list[dict], day: str,
                  votes_by_id: dict | None = None, own: dict | None = None, topic_labels: dict | None = None,
                  bench: dict | None = None, activity: dict | None = None, presence: dict | None = None) -> dict:
    st = stats["meps"][str(mep["id"])]
    meps_by_id = {m["id"]: m for m in meps}
    votes_by_id = votes_by_id or {v["id"]: v for v in votes}
    with_vote = lambda x: {**vote_summary(votes_by_id[x["id"]], meps_by_id), **x}
    ag = st.get("against_group", {"count": 0, "count_main": 0, "recent": [], "recent_main": []})
    by_id = {str(m["id"]): m for m in meps}
    pairwise = sorted(
        ({**mep_summary(by_id[k], day), "same": v[0], "total": v[1]} for k, v in st["pairwise"].items() if k in by_id),
        key=lambda x: (-(x["same"] / x["total"]) if x["total"] else 1, x["id"]),
    )
    return {
        "mep": mep,
        "short_mandate": mandate_days(mep["mandates"], day) < SHORT_MANDATE_DAYS,
        "mandate_days": mandate_days(mep["mandates"], day),
        "sources": stats["sources"],
        "definitions": stats["definitions"],
        "total": st["total"],
        "monthly": st["monthly"],
        "pairwise": pairwise,
        "recent_main_votes": recent_main_votes(mep, votes),
        "benchmarks": mep_benchmarks(mep, votes, bench),
        "against_group": {"count": ag["count"], "count_main": ag["count_main"],
                          **{k: ag.get(k) for k in ("party_known", "with_party", "party_known_main", "with_party_main")},
                          "recent": [with_vote(x) for x in ag["recent"]],
                          "recent_main": [with_vote(x) for x in ag["recent_main"]]},
        "decisive": [with_vote(x) for x in st.get("decisive", [])],
        "topics": topic_rows(st.get("topics", {}), stats.get("topics", []), topic_labels),
        "activity": activity,
        "presence": presence,
        "own_work": None if own is None else {
            "source": own["source"], "updated": own["updated"], "complete": own["complete"],
            "type_labels": own["type_labels"],
            **own["meps"].get(str(mep["id"]), {"summary": {}, "items": []}),
        },
    }


def build_decisive(stats: dict, votes_by_id: dict, meps_by_id: dict) -> dict:
    va = stats["votes_analysis"]
    return {
        "sources": stats["sources"], "close_margin": CLOSE_MARGIN,
        "close_count": va["close"]["count"], "close_count_main": va["close"]["count_main"],
        "decisive_final": sum(is_final(votes_by_id[d["id"]]) for d in va["decisive"]),
        "definition": stats["definitions"].get("decisive_votes"), "kind_labels": KIND_LABELS,
        "votes": [{**vote_summary(votes_by_id[d["id"]], meps_by_id), "alternative_result": d["alternative_result"],
                   "positions": cz_positions(votes_by_id[d["id"]], meps_by_id)} for d in va["decisive"]],
    }


def build_splits(stats: dict, votes_by_id: dict, meps_by_id: dict) -> dict:
    sp = stats["votes_analysis"]["splits"]
    # Pozice jen jako {ID poslance: volba} a frakce k datu hlasování {ID: kód}, aby soubor zůstal malý.
    def item(x):
        pos = cz_positions(votes_by_id[x["id"]], meps_by_id)
        return {**vote_summary(votes_by_id[x["id"]], meps_by_id), "split": x["split"],
                "positions": {str(p["member_id"]): p["position"] for p in pos},
                "groups": {str(p["member_id"]): p["group_code"] for p in pos}}
    ls = sp["last_session"]
    return {
        "sources": stats["sources"], "count": sp["count"], "count_main": sp["count_main"],
        "unity": stats["votes_analysis"].get("unity"),
        "last_session": {"from": ls["from"], "to": ls["to"], "votes": ls["votes"], "split_count": len(ls["split"]),
                         "split": [item(x) for x in ls["split"][:LAST_SESSION_LIMIT]]},
        "all": [item(x) for x in sp["all"]],
        "main": [item(x) for x in sp["main"]],
    }


def build_session(stats: dict, votes: list[dict], votes_by_id: dict, meps_by_id: dict, top: int = 5) -> dict:
    """Shrnutí posledního zasedání: počty, kde se Češi nejvíc rozdělili, rozhodující a těsná hlasování."""
    ls = stats["votes_analysis"]["splits"]["last_session"]
    in_session = [v for v in votes if ls["from"] and ls["from"] <= v["date"] <= ls["to"]]
    close_ids = set(stats["votes_analysis"]["close"]["ids"])
    decisive = [d for d in stats["votes_analysis"]["decisive"] if d["id"] in {v["id"] for v in in_session}]
    item = lambda vid, **kw: {**vote_summary(votes_by_id[vid], meps_by_id), **kw}
    return {
        "sources": stats["sources"], "from": ls["from"], "to": ls["to"],
        "votes": len(in_session), "main": sum(is_final(v) for v in in_session),
        "adopted_main": sum(is_final(v) and v.get("result") == "ADOPTED" for v in in_session),
        "split_count": len(ls["split"]),
        "unity": (stats["votes_analysis"].get("unity") or {}).get("last_session"),
        "unity_all": {k: v for k, v in (stats["votes_analysis"].get("unity") or {}).items() if k != "last_session"},
        "decisive_final": sum(is_final(votes_by_id[d["id"]]) for d in decisive),
        "close_count": sum(v["id"] in close_ids for v in in_session),
        "top_splits": [item(x["id"], split=x["split"]) for x in ls["split"][:top]],
        "top_splits_main": [item(x["id"], split=x["split"]) for x in ls["split"] if x.get("is_final", x.get("is_main"))][:top],
        "decisive": [item(d["id"], alternative_result=d["alternative_result"]) for d in decisive],
    }


PASSED_KEYS = ["lead_adopted", "lead_adopted_legislative", "lead_pending", "shadow_adopted",
               "shadow_adopted_legislative", "shadow_pending", "resolutions_adopted"]


ROLE_KEYS = ["lead_reports", "lead_opinions", "shadow_reports", "shadow_opinions", "motions_signed"]


# Funkce, které EP uvádí u členství ve výboru nebo frakci (fetch_meps.py). Řadové členství se neukazuje.
FUNCTION_ROLES = {"committee": ("CHAIR", "CHAIR_VICE"), "group": ("CHAIR", "CHAIR_VICE", "MEMBER_BUREAU")}


def functions(m: dict, day: str) -> list[dict]:
    """Funkce platné k danému dni: předseda/místopředseda výboru, předseda/místopředseda/předsednictvo frakce."""
    active = lambda x: x["start"] <= day and (x["end"] is None or day <= x["end"])
    out = [{"kind": "committee", "role": x["role"], "code": x["code"], "name_cs": x.get("name_cs")}
           for x in m.get("committees", []) if x.get("role") in FUNCTION_ROLES["committee"] and active(x)]
    out += [{"kind": "group", "role": x["role"], "code": x["code"], "name_cs": x.get("name_cs")}
            for x in m.get("groups", []) if x.get("role") in FUNCTION_ROLES["group"] and active(x)]
    order = {"CHAIR": 0, "CHAIR_VICE": 1, "MEMBER_BUREAU": 2}
    return sorted(out, key=lambda f: (f["kind"] != "committee", order[f["role"]], f["code"] or ""))


def activity_by_mep(meps: list[dict], speeches: dict | None) -> dict[int, dict]:
    """Projevy v plénu po poslancích v době mandátu (activity.count_activity z data/speeches.json); {} bez souboru."""
    if not speeches:
        return {}
    return {m["id"]: count_activity(speeches["meps"].get(str(m["id"]), []), m["mandates"]) for m in meps}


def presence_by_mep(meps: list[dict], attendance: dict | None) -> dict[int, dict]:
    """Prezence na zasedání podle prezenční listiny EP po poslancích v době mandátu (attendance.count_presence); {} bez souboru."""
    if not attendance:
        return {}
    return {m["id"]: count_presence(attendance["days"], m["id"], m["mandates"]) for m in meps}


def build_work(meps: list[dict], own: dict | None, day: str, stats: dict | None = None,
               activity: dict[int, dict] | None = None, presence: dict[int, dict] | None = None) -> dict | None:
    """Profil vlastní práce: počty z own_work.json (spočítal own_work.passed / roles / delegation_profile),
    docházka ze stats.json a funkce z meps.json, nic nového."""
    if own is None:
        return None
    rows = []
    for m in meps:
        entry = own["meps"].get(str(m["id"])) or {}
        passed = entry.get("passed") or {}
        roles = entry.get("roles") or {}
        total = ((stats or {}).get("meps", {}).get(str(m["id"])) or {}).get("total") or {}
        rows.append({**mep_summary(m, day), **{k: passed.get(k, 0) for k in PASSED_KEYS},
                     **{k: roles.get(k, 0) for k in ROLE_KEYS}, "delegation": roles.get("delegation"),
                     "attendance": total.get("attendance"), "functions": functions(m, day),
                     **{k: (activity or {}).get(m["id"], {}).get(k) for k in ("speeches", "speeches_minutes", "written_statements")},
                     "presence": (presence or {}).get(m["id"])})
    return {"source": own["source"], "updated": own["updated"], "complete": own["complete"], "meps": rows}


def build_vote_roles(own: dict | None) -> dict[str, list[dict]]:
    """Česká stopa u hlasování (F3): kdo z českých poslanců byl zpravodajem a kdo stínovým zpravodajem zprávy, o které se
    hlasovalo (z own_work.json, který vazbu zprávy na závěrečné hlasování určil). {id hlasování: [{mep_id, role}]}."""
    out: dict[str, list[dict]] = {}
    for mep_id, entry in (own or {}).get("meps", {}).items():
        for it in entry.get("items", []):
            if it["type"] in ("report", "shadow_report") and it.get("vote_id"):
                role = "shadow" if it["type"] == "shadow_report" else ("co" if it.get("role") == "RAPPORTEUR_CO" else "rapporteur")
                row = {"mep_id": int(mep_id), "role": role, "report": it.get("report"), "procedure": it.get("label")}
                if row not in out.setdefault(str(it["vote_id"]), []):
                    out[str(it["vote_id"])].append(row)
    for rows in out.values():
        rows.sort(key=lambda r: (r["role"] == "shadow", r["mep_id"]))
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def build_agreement(meps: list[dict], stats: dict, day: str) -> dict:
    """Matice shody: pro každou dvojici [stejně, oba hlasovali]."""
    return {
        "sources": stats["sources"], "definition": stats["definitions"].get("pairwise"),
        "meps": [mep_summary(m, day) for m in sorted(meps, key=lambda m: m.get("sort_label") or m["name"])],
        "matrix": {str(m["id"]): stats["meps"][str(m["id"])]["pairwise"] for m in meps},
    }


def party_reports(pid: str, meps: list[dict], own: dict | None) -> dict | None:
    """Zprávy, které vedli poslanci strany (D6): zpravodaj/ka nebo spoluzpravodaj/ka podle own_work.json a počet stínových zpráv.
    Strana se bere k datu zprávy (období ve straně podle EP), bez pořadí a bez hodnocení. Bez own_work.json None."""
    if not own:
        return None
    in_party = lambda m, d: bool(d) and any(p["org_id"] == pid and p["start"] <= d and (not p.get("end") or d <= p["end"])
                                            for p in m["parties"])
    reports, shadow = [], 0
    for m in meps:
        for it in (own["meps"].get(str(m["id"])) or {}).get("items", []):
            if it.get("type") not in ("report", "shadow_report") or not in_party(m, it.get("date")):
                continue
            if it["type"] == "shadow_report":
                shadow += 1
                continue
            reports.append({"mep_id": m["id"], "role": "co" if it.get("role") == "RAPPORTEUR_CO" else "rapporteur",
                            "label": it.get("label"), "title_cs": (it.get("title") or {}).get("cs"), "url": it.get("url"),
                            "date": it["date"], "status": it.get("status"), "vote_id": it.get("vote_id")})
    reports.sort(key=lambda r: (r["date"], r["label"] or ""), reverse=True)
    return {"items": reports, "shadow_count": shadow, "source": own["source"], "updated": own.get("updated")}


def build_parties_web(stats: dict, parties: list[dict], meps: list[dict], votes_by_id: dict, day: str,
                      own: dict | None = None) -> tuple:
    meps_by_id = {m["id"]: m for m in meps}
    index, pages = [], {}
    for party in parties:
        pid = str(party["id"])
        if party.get("independent") or pid not in stats.get("parties", {}):
            continue
        st = stats["parties"][pid]
        members = []
        for m in meps:
            periods = [{"start": p["start"], "end": p["end"]} for p in m["parties"] if p["org_id"] == pid]
            if periods:
                members.append({**mep_summary(m, day), "party_periods": periods,
                                "total": stats["meps"][str(m["id"])]["total"]})
        summary = {**party, "members": len(members), "total": st["total"], "cohesion": st["cohesion"],
                   "cohesion_main": st["cohesion_main"], "splits_count": st["splits"]["count"],
                   "splits_count_main": st["splits"]["count_main"]}
        index.append(summary)
        split_item = lambda vid: {**vote_summary(votes_by_id[vid], meps_by_id),
                                  "positions": [p for p in cz_positions(votes_by_id[vid], meps_by_id)
                                                if str(p["national_party_id"]) == pid]}
        pages[pid] = {**summary, "sources": stats["sources"], "definitions": stats["definitions"],
                      "member_list": members, "reports": party_reports(pid, meps, own),
                      "splits": [split_item(v) for v in st["splits"]["recent"]],
                      "splits_main": [split_item(v) for v in st["splits"]["recent_main"]]}
    return {"sources": stats["sources"], "parties": index}, pages


def build_eu_groups(votes: list[dict], votes_by_id: dict, meps: list[dict], stats: dict, groups: list[dict],
                    group_web: dict | None, day: str) -> tuple[dict, dict]:
    """Politické skupiny EP (index + stránky): souhrn celé skupiny z group_counts a čeští členové (data/eugroups/)."""
    gs = build_group_stats(votes)
    by_ep = {g.get("ep_code"): g["code"] for g in groups}
    meps_by_id = {m["id"]: m for m in meps}
    index, pages = [], {}
    for g in groups:
        code = g["code"]
        if code not in gs:
            continue
        members = []
        for m in meps:
            cur = current(m["groups"], day)
            if any(x["end"] is None for x in m["mandates"]) and cur and by_ep.get(cur["code"], cur["code"]) == code:
                members.append({**mep_summary(m, day), "total": stats["meps"][str(m["id"])]["total"]})
        st = gs[code]
        row = lambda vid: {**vote_summary(votes_by_id[vid], meps_by_id), "gc": votes_by_id[vid]["group_counts"][code]}
        summary = {**{k: g.get(k) for k in ("code", "short_label", "name_cs", "label", "color", "chart_color", "logo", "logo_aspect")},
                   "web": ((group_web or {}).get("groups") or {}).get(code, {}).get("web"), "cz_members": len(members),
                   "attendance": st["attendance"], "attendance_main": st["attendance_main"], "majority": st["majority"],
                   "majority_main": st["majority_main"], "splits": st["splits"], "considered": st["considered"],
                   "splits_main": st["splits_main"], "considered_main": st["considered_main"]}
        index.append(summary)
        pages[code] = {**summary, "sources": stats["sources"], "member_list": members,
                       "splits_list": [row(v) for v in st["split_ids"]], "splits_list_main": [row(v) for v in st["split_ids_main"]]}
    index.sort(key=lambda r: (-r["cz_members"], r["short_label"]))
    web_src = (group_web or {}).get("source")
    return {"sources": {**stats["sources"], **({"group_web": web_src} if web_src else {})}, "groups": index}, pages


POSITION_LETTER = {"FOR": "F", "AGAINST": "A", "ABSTENTION": "B", "DID_NOT_VOTE": "N"}


def mep_votes(mep: dict, votes: list[dict]) -> dict:
    """Hlas poslance u všech hlasování v době jeho mandátu (data/meps/{id}_votes.json): ids a řetězec písmen F/A/B/N
    (pro, proti, zdržel se, nehlasoval) ve stejném pořadí. Slouží filtru „Poslanec“ v seznamu hlasování."""
    ids, letters = [], []
    for v in votes:
        if not in_mandate(mep["mandates"], v["date"]):
            continue
        for p in v["cz_positions"]:
            if p["member_id"] == mep["id"]:
                ids.append(v["id"])
                letters.append(POSITION_LETTER[p["position"]])
                break
    return {"ids": ids, "positions": "".join(letters)}


STALE_DAYS = 14


def build_freshness(release: str | None, agenda: dict | None) -> dict:
    """Podklad pro pruh „data mohou být neaktuální“ (rozhodnutí autora 16. 10. 2026): datum exportu a plenární dny po něm.
    Prohlížeč pruh ukáže, když je export starší než STALE_DAYS dní a od té doby už nějaké zasedání proběhlo
    (bez zasedání nová hlasování být nemohou, stará data jsou pak aktuální)."""
    day = release[:10] if release and len(release) >= 10 else None
    sittings = (agenda or {}).get("sittings") or []
    return {"note": "Datum exportu hlasování a plenární dny po něm (EP Open Data API). Generuje scripts/build_web.py.",
            "release": day, "stale_days": STALE_DAYS,
            "sittings_after": sorted(d for d in sittings if day and d > day)}


def write_json(path: Path, obj, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else \
        json.dumps(obj, ensure_ascii=False, indent=1)
    path.write_text(text + "\n", encoding="utf-8")


def run(data_dir: Path, day: str) -> dict:
    meps_doc = json.loads((data_dir / "meps.json").read_text(encoding="utf-8"))
    stats = json.loads((data_dir / "stats.json").read_text(encoding="utf-8"))
    require(meps_doc, ["meps"], "meps.json")
    require(stats, ["meps", "sources", "period", "votes_total", "definitions"], "stats.json")
    meps = meps_doc["meps"]
    apply_name_overrides(meps, data_dir / "manual" / "overrides.json")
    missing = [m["id"] for m in meps if str(m["id"]) not in stats["meps"]]
    if missing:
        raise FormatError(f"stats.json nemá poslance {missing}, spusť nejdřív compute_stats.py")
    index, votes = load_votes(data_dir / "votes")
    topic_labels = load_topic_labels(data_dir / "manual" / "topics_cs.json")
    by_id = {m["id"]: m for m in meps}
    votes_by_id = {v["id"]: v for v in votes}
    parties = json.loads((data_dir / "parties.json").read_text(encoding="utf-8"))
    own_path = data_dir / "own_work.json"
    own = json.loads(own_path.read_text(encoding="utf-8")) if own_path.exists() else None
    speeches_path = data_dir / "speeches.json"
    speeches = json.loads(speeches_path.read_text(encoding="utf-8")) if speeches_path.exists() else None
    if speeches is not None:
        require(speeches, ["meps", "source"], "speeches.json")
    attendance_path = data_dir / "attendance.json"
    attendance = json.loads(attendance_path.read_text(encoding="utf-8")) if attendance_path.exists() else None
    if attendance is not None:
        require(attendance, ["days", "source"], "attendance.json")
    presence = presence_by_mep(meps, attendance)
    presence_info = {"source": attendance["source"], "updated": attendance.get("updated")} if attendance else None
    activity = activity_by_mep(meps, speeches)
    activity_info = {"source": speeches["source"], "updated": speeches.get("updated")} if speeches else None
    bench_path = data_dir / "benchmarks.json"
    bench = json.loads(bench_path.read_text(encoding="utf-8")) if bench_path.exists() else None
    if bench is not None:
        require(bench, ["ep", "groups"], "benchmarks.json")

    key = build_key_votes(votes, by_id)
    key["sources"] = stats["sources"]
    write_json(data_dir / "key_votes.json", key)
    write_json(data_dir / "overview.json", build_overview(meps, stats, day, topic_labels, bench))
    write_json(data_dir / "agreement.json", build_agreement(meps, stats, day), compact=True)
    if own is not None:
        write_json(data_dir / "vote_roles.json", {"source": own["source"], "updated": own["updated"],
                                                  "votes": build_vote_roles(own)}, compact=True)
    work = build_work(meps, own, day, stats, activity, presence)
    if own is not None:
        info = {m["id"]: mep_summary(m, day) for m in meps}
        hub = build_work_hub(own, meps, info, speeches, attendance)
        hub["sources"] = {"own_work": own["source"], "speeches": (activity_info or {}).get("source"), "presence": (presence_info or {}).get("source")}
        write_json(data_dir / "work_hub.json", hub)
    if work is not None and activity_info:
        work["activity_source"] = activity_info
    if work is not None and presence_info:
        work["presence_source"] = presence_info
    if work is not None and bench is not None:
        work["attendance_ep_median"] = bench["ep"].get("attendance")
    if work is not None:
        write_json(data_dir / "work.json", work)
    profiles_dir = data_dir / "meps"
    for m in meps:
        write_json(profiles_dir / f"{m['id']}.json", build_profile(m, meps, stats, votes, day, votes_by_id, own,
                                                                      topic_labels, bench,
                                                                      {**activity[m["id"]], **activity_info} if activity_info else None,
                                                                      {**presence[m["id"]], **presence_info} if presence_info else None))
    for m in meps:
        write_json(profiles_dir / f"{m['id']}_votes.json", mep_votes(m, votes), compact=True)
    if "votes_analysis" in stats:
        write_json(data_dir / "decisive.json", build_decisive(stats, votes_by_id, by_id))
        write_json(data_dir / "splits.json", build_splits(stats, votes_by_id, by_id))
        write_json(data_dir / "category_stats.json", {**category_stats(
            votes, by_id, {int(k) for k in build_vote_roles(own)} if own else None), "sources": stats["sources"]})
        write_json(data_dir / "categories.json", {k: {"label": n, "icon": icon_inner(k)} for k, n, _ in CATEGORIES})
        write_json(data_dir / "session.json", build_session(stats, votes, votes_by_id, by_id))
        gw_path, groups_path = data_dir / "group_web.json", data_dir / "groups.json"
        if groups_path.exists():
            eu_index, eu_pages = build_eu_groups(votes, votes_by_id, meps, stats, json.loads(groups_path.read_text(encoding="utf-8")),
                                                 json.loads(gw_path.read_text(encoding="utf-8")) if gw_path.exists() else None, day)
            write_json(data_dir / "eugroups" / "index.json", eu_index)
            for code, page in eu_pages.items():
                write_json(data_dir / "eugroups" / f"{code}.json", page)
        party_index, party_pages = build_parties_web(stats, parties, meps, votes_by_id, day, own)
        write_json(data_dir / "parties" / "index.json", party_index)
        for pid, page in party_pages.items():
            write_json(data_dir / "parties" / f"{pid}.json", page)
    # Jedno hlasování na řádek kvůli čitelným diffům.
    search = build_search(votes, by_id, topic_labels, index.get("oeil_subjects"))
    lines = [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in search["rows"]]
    head = json.dumps({k: v for k, v in search.items() if k != "rows"}, ensure_ascii=False, separators=(",", ":"))
    (data_dir / "votes" / "search.json").write_text(head[:-1] + ',"rows":[\n' + ",\n".join(lines) + "\n]}\n",
                                                    encoding="utf-8")
    # Témata (kategorie) všech hlasování pro detail vote.html: stejná funkce jako čip v seznamu (categories_for), jen neprázdné.
    write_json(data_dir / "vote_cats.json", {"note": "Klíče kategorií hlasování (scripts/categories.py), první = hlavní.",
                                             "votes": {str(v["id"]): c for v in votes if (c := categories_for(v))}}, compact=True)
    agenda_path = data_dir / "agenda.json"
    write_json(data_dir / "freshness.json", build_freshness(
        stats["sources"].get("votes", {}).get("release"),
        json.loads(agenda_path.read_text(encoding="utf-8")) if agenda_path.exists() else None))
    return {"profiles": len(meps), "votes": len(votes)}


def main(argv=None) -> int:
    import datetime as dt
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    p.add_argument("--today", default=dt.datetime.now(dt.timezone.utc).date().isoformat(),
                   help="den, ke kterému se určí aktuální frakce a strana")
    args = p.parse_args(argv)
    try:
        res = run(args.data_dir, args.today)
        # Úvodní stránka (data/home.json): pět nejnovějších závěrečných hlasování a čísla pro pruh faktů.
        from build_home import build as build_home
        home = build_home(args.data_dir)
        (args.data_dir / "home.json").write_text(json.dumps(home, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    print(f"web: {res['profiles']} profilů, {res['votes']} hlasování v search.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
