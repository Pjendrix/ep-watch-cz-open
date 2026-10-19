"""Radar „Co se chystá“: nejbližší zasedání a legislativní procedury s českou stopou (data/radar.json).

Nic se nestahuje ani neodhaduje, jen se spojují soubory, které už existují:
- data/agenda.json (fetch_agenda.py): program nejbližšího zasedání, fáze bodu, procedura a výbor u zpráv;
- data/proposals.json (fetch_proposals.py): procedury s českou účastí, jejich události a odpovědný výbor;
- data/proposals_state.json: čísla procedur (label) a vazba zpráva -> procedura;
- data/own_work.json (compute_stats.py): česká stopa u bodů programu (zpravodaj, stínový zpravodaj);
- data/votes/ (HowTheyVote): poslední závěrečné hlasování procedury (podle čísla procedury) pro odkaz na výsledek.

Pravidla (vypsaná i na webu, o-projektu#radar):
- Stav procedury se určuje z jejích událostí podle pevné tabulky MILESTONES, časová osa podle tabulky AXIS (skutečné
  milníky s vlastním datem, 1. a 2. čtení, podpis a vyhlášení zvlášť). Pole current_stage z EP API se nepoužívá,
  protože u uzavřených procedur zůstává „první čtení“.
- „Rozpracované“ = legislativní procedura (COD, CNS, APP) s českou rolí, o které ještě nehlasovalo plénum.
  Řazení: nejblíž hlasování (dosažený krok), pak podle poslední události.
- „Odhlasované“ = hlasovalo plénum (posledních DONE_DAYS dní), s odkazem na výsledek.
- Kategorie = odpovědný výbor podle tabulky COMMITTEE_CATEGORY (bez výboru nebo mimo tabulku: bez kategorie).
- Datum budoucího hlasování je jen z programu zasedání; jinak None („zatím nezveřejněno“).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from agenda import ROLE_CS, cz_roles_by_doc, doc_key
from overrides import apply_name_overrides
from vote_kinds import is_final
from compute_stats import load_votes

LEGISLATIVE = {"COD", "CNS", "APP"}  # stejně jako own_work.py
DONE_DAYS = 365
CZ_ROLES = {
    "RAPPORTEUR": "rapporteur",
    "RAPPORTEUR_CO": "co",
    "RAPPORTEUR_SHADOW": "shadow",
    "RAPPORTEUR_OPINION": "opinion",
    "RAPPORTEUR_SHADOW_OPINION": "shadow_opinion",
}
CZ_ROLE_CS = {**ROLE_CS, "opinion": "zpravodaj/ka stanoviska", "shadow_opinion": "stínový/á zpravodaj/ka stanoviska"}
ROLE_ORDER = ["rapporteur", "co", "shadow", "opinion", "shadow_opinion"]

# Fáze procedury: oficiální české názvy z číselníku EU „procedure-phase“
# (https://publications.europa.eu/resource/authority/procedure-phase).
STAGE_CS = {
    "PROP": "návrh",
    "INI_LEGIS": "legislativní podnět",
    "RDG1": "první čtení",
    "RDG2": "druhé čtení",
    "RDG3": "třetí čtení",
    "NGT": "jednání",
    "CONCILIA": "dohodovací postup",
    "CONCILIA_RDG3": "dohodovací postup a třetí čtení",
    "PROC_END": "konec postupu",
}

# Fáze procedury pro stav na radaru (rozpracovaná / odhlasovaná, řazení): (klíč, název, typy událostí EP API). Pořadí = průběh.
# Název fáze se ukazuje jen u kroků, které procedura teprve čeká (FUTURE_STEPS); hotové kroky mají vlastní popisek (AXIS).
MILESTONES = [
    (
        "committee",
        "Výbor",
        {"REFERRAL", "COMMITTEE_TABLING_REPORT", "COMMITTEE_TABLING_AMENDMENT", "COMMITTEE_TABLING_OPINION", "COMMITTEE_ADOPTING_OPINION"},
    ),
    ("report", "Hlasování ve výboru", {"COMMITTEE_ADOPTING_REPORT", "TABLING_PLENARY"}),
    (
        "trilogue",
        "Jednání s Radou",
        {
            "PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS",
            "PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS",
            "PLENARY_REJECT_COMMITTEE_INTERINSTUTIONAL_NEGOTIATIONS",
            "INTERINSTITUTIONAL_NEGOTIATION",
            "COMMITTEE_APPROVE_PROVISIONAL_AGREEMENT",
            "PLENARY_AMEND",
        },
    ),
    (
        "plenary",
        "Hlasování pléna",
        {
            "PLENARY_ADOPT_POSITION",
            "PLENARY_APPROVE_COUNCIL_POSITION",
            "PLENARY_AMEND_COUNCIL_POSITION",
            "PLENARY_AMEND_PROPOSAL",
            "PLENARY_DECISION",
        },
    ),
    ("closed", "Podpis a vyhlášení", {"SIGNATURE", "PUBLICATION_OFFICIAL_JOURNAL"}),
]
MILESTONE_KEYS = [k for k, _, _ in MILESTONES]
# Obecné „hlasování v plénu“ (Activity bez rozhodnutí) nic neurčuje: provází rozhodnutí pléna, ale EP ho zveřejňuje i samostatně,
# typicky pár dní po přidělení výboru (2024/0061(COD) 13. 3. 2025). O čem se hlasovalo, API neříká, proto ho nepočítáme
# jako hlasování o zákoně ani ho nedáváme na časovou osu (v seznamu událostí na stránce Příběh zákona zůstává).
GENERIC_VOTE = {"PLENARY_VOTE", "PLENARY_VOTE_RESULTS"}

# Časová osa = skutečné milníky v pořadí, jak proběhly, každý s vlastním datem: typ události -> český popisek.
# Ostatní události (návrhy zpráv, stanoviska, rozpravy, obecná hlasování) na osu nejdou, jen do seznamu událostí.
# Čtení se neodhaduje, plyne z typu: postoj EP k návrhu = 1. čtení, hlasování o postoji Rady = 2. čtení (řádný postup, COD).
READING_1 = {"PLENARY_ADOPT_POSITION", "PLENARY_AMEND_PROPOSAL"}
READING_2 = {"PLENARY_APPROVE_COUNCIL_POSITION", "PLENARY_AMEND_COUNCIL_POSITION"}
AXIS = {
    "REFERRAL": "Přiděleno výboru",
    "COMMITTEE_ADOPTING_REPORT": "Hlasování ve výboru",
    "TABLING_PLENARY": "Zpráva předložena plénu",
    "PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS": "Plénum potvrdilo mandát k jednání s Radou",
    "PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS": "Plénum vrátilo zprávu výboru k jednání s Radou",
    "PLENARY_REJECT_COMMITTEE_INTERINSTUTIONAL_NEGOTIATIONS": "Plénum odmítlo mandát k jednání s Radou",
    "PLENARY_AMEND": "Plénum přijalo pozměňovací návrhy",
    "INTERINSTITUTIONAL_NEGOTIATION": "Jednání s Radou (trialog)",
    "COMMITTEE_APPROVE_PROVISIONAL_AGREEMENT": "Výbor schválil dohodu s Radou",
    "PLENARY_ADOPT_POSITION": "Hlasování pléna",
    "PLENARY_AMEND_PROPOSAL": "Hlasování pléna",
    "PLENARY_APPROVE_COUNCIL_POSITION": "Hlasování pléna – 2.\u00a0čtení (schválen postoj Rady)",
    "PLENARY_AMEND_COUNCIL_POSITION": "Hlasování pléna – 2.\u00a0čtení (pozměněn postoj Rady)",
    "PLENARY_DECISION": "Rozhodnutí pléna",
    "SIGNATURE": "Podpis aktu",
    "PUBLICATION_OFFICIAL_JOURNAL": "Vyhlášení v Úředním věstníku",
}
# Kroky, které procedura ještě čeká (šedě za posledním milníkem). Jednání s Radou není povinné, proto mezi nimi není.
FUTURE_STEPS = ["report", "plenary", "closed"]

# Události v češtině (poslední událost u procedury). Neznámý typ se nepřekládá odhadem: vypíše se v radar.json
# (unmapped_events) a test na to upozorní.
EVENT_CS = {
    "REFERRAL": "přiděleno výboru",
    "COMMITTEE_TABLING_REPORT": "návrh zprávy ve výboru",
    "COMMITTEE_TABLING_AMENDMENT": "pozměňovací návrhy ve výboru",
    "COMMITTEE_TABLING_OPINION": "návrh stanoviska výboru",
    "COMMITTEE_ADOPTING_OPINION": "výbor přijal stanovisko",
    "COMMITTEE_ADOPTING_REPORT": "výbor přijal zprávu",
    "TABLING_PLENARY": "zpráva předložena plénu",
    "PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS": "plénum potvrdilo mandát k jednání s Radou",
    "PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS": "plénum vrátilo zprávu výboru k jednání s Radou",
    "PLENARY_REJECT_COMMITTEE_INTERINSTUTIONAL_NEGOTIATIONS": "plénum odmítlo mandát výboru k jednání s Radou",
    "INTERINSTITUTIONAL_NEGOTIATION": "jednání s Radou (trialog)",
    "COMMITTEE_APPROVE_PROVISIONAL_AGREEMENT": "výbor schválil dohodu s Radou",
    "PLENARY_AMEND": "plénum přijalo pozměňovací návrhy",
    "PLENARY_DEBATE": "rozprava v plénu",
    "PLENARY_VOTE": "hlasování v plénu",
    "PLENARY_VOTE_RESULTS": "výsledky hlasování v plénu",
    "PLENARY_ADOPT_POSITION": "plénum přijalo postoj",
    "PLENARY_APPROVE_COUNCIL_POSITION": "plénum schválilo postoj Rady",
    "PLENARY_AMEND_COUNCIL_POSITION": "plénum pozměnilo postoj Rady",
    "PLENARY_AMEND_PROPOSAL": "plénum přijalo pozměňovací návrhy k návrhu",
    "PLENARY_DECISION": "rozhodnutí pléna",
    "SIGNATURE": "podpis aktu",
    "PUBLICATION_OFFICIAL_JOURNAL": "vyhlášení v Úředním věstníku",
}

# Výbory EP 10. období: český název a kategorie webu (scripts/categories.py). Kategorie podle hlavní náplně výboru;
# výbor bez jednoznačné kategorie (CULT) kategorii nemá.
COMMITTEES = {
    "AFET": ("Zahraniční věci", "abr"),
    "DROI": ("Lidská práva", "abr"),
    "SEDE": ("Bezpečnost a obrana", "def"),
    "DEVE": ("Rozvoj", "abr"),
    "INTA": ("Mezinárodní obchod", "abr"),
    "BUDG": ("Rozpočty", "fin"),
    "CONT": ("Kontrola rozpočtu", "fin"),
    "ECON": ("Hospodářské a měnové věci", "fin"),
    "FISC": ("Daňové záležitosti", "fin"),
    "EMPL": ("Zaměstnanost a sociální věci", "soc"),
    "ENVI": ("Životní prostředí, klima a bezpečnost potravin", "env"),
    "SANT": ("Veřejné zdraví", "soc"),
    "ITRE": ("Průmysl, výzkum a energetika", "eco"),
    "IMCO": ("Vnitřní trh a ochrana spotřebitelů", "eco"),
    "TRAN": ("Doprava a cestovní ruch", "tra"),
    "REGI": ("Regionální rozvoj", "fin"),
    "AGRI": ("Zemědělství a rozvoj venkova", "agr"),
    "PECH": ("Rybolov", "agr"),
    "CULT": ("Kultura a vzdělávání", None),
    "JURI": ("Právní záležitosti", "jus"),
    "LIBE": ("Občanské svobody, spravedlnost a vnitřní věci", "jus"),
    "AFCO": ("Ústavní záležitosti", "ins"),
    "FEMM": ("Práva žen a rovnost pohlaví", "civ"),
    "PETI": ("Petice", "ins"),
    "HOUS": ("Bydlení", "soc"),
    "EUDS": ("Evropský štít demokracie", "ins"),
}
OEIL_URL = "https://oeil.secure.europarl.europa.eu/oeil/en/procedure-file?reference={label}"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _name(m: dict) -> str:
    return f"{m['given_name']} {m['family_name']}" if m.get("given_name") and m.get("family_name") else m["name"]


def process_type(label: str | None) -> str | None:
    """2023/0436(COD) -> COD."""
    return label.rsplit("(", 1)[-1].rstrip(")") if label and label.endswith(")") and "(" in label else None


def committee_info(code: str | None) -> dict | None:
    if not code:
        return None
    name, cat = COMMITTEES.get(code, (None, None))
    return {"code": code, "name": name, "category": cat}


def axis_label(event_type: str, process_type: str | None) -> str:
    if event_type in READING_1 and process_type == "COD":
        return "Hlasování pléna – 1.\u00a0čtení"
    return AXIS[event_type]


def axis(events: list[dict], process_type: str | None = None) -> list[dict]:
    """Milníky časové osy v pořadí: [{type, label, date, date_to?}]. Stejné události po sobě (trialogy, předložení plénu
    několik dní za sebou) se slučují do jednoho milníku s rozsahem dat. Pozměňovací návrhy pléna ve dni, kdy plénum vrátilo
    zprávu výboru, jsou součástí toho kroku a zvlášť se neukazují."""
    days_refer = {e["date"] for e in events if e["type"] == "PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS"}
    order = list(AXIS)
    picked = sorted(
        {(e["date"], e["type"]) for e in events if e["type"] in AXIS and not (e["type"] == "PLENARY_AMEND" and e["date"] in days_refer)},
        key=lambda x: (x[0], order.index(x[1])),
    )
    out: list[dict] = []
    for date, typ in picked:
        if out and out[-1]["type"] == typ:
            out[-1]["date_to"] = date
            continue
        out.append({"type": typ, "label": axis_label(typ, process_type), "date": date})
    return out


def timeline(events: list[dict], process_type: str | None = None) -> dict:
    """Stav a časová osa procedury z událostí: {steps, reached, plenary_date, last_event, unmapped}.

    steps = skutečné milníky (axis) s datem a za nimi kroky, které procedura ještě čeká (bez data, FUTURE_STEPS).
    reached = fáze poslední události (procedura se může vracet: po hlasování v plénu znovu jednání s Radou).
    V den poslední události rozhoduje nejvyšší fáze; obecná hlasování (GENERIC_VOTE) fázi neurčují."""
    stage_of = {t: i for i, (_, _, types) in enumerate(MILESTONES) for t in types}
    unmapped = sorted({e["type"] for e in events if e["type"] not in stage_of and e["type"] not in EVENT_CS})
    marked = [e for e in events if e["type"] in stage_of]
    reached = None
    if marked:
        day = max(e["date"] for e in marked)
        reached = max(stage_of[e["type"]] for e in marked if e["date"] == day)
    steps = [{"key": MILESTONE_KEYS[stage_of[m["type"]]], **m} for m in axis(events, process_type)]
    if reached is not None and MILESTONE_KEYS[reached] != "closed":
        steps += [
            {"key": k, "type": None, "label": MILESTONES[i][1], "date": None}
            for i, k in enumerate(MILESTONE_KEYS)
            if k in FUTURE_STEPS and i > reached
        ]
    plenary = [e["date"] for e in marked if stage_of[e["type"]] == 3]
    last = next(
        (
            {"date": e["date"], "type": e["type"], "label": EVENT_CS[e["type"]]}
            for e in sorted(events, key=lambda e: e["date"], reverse=True)
            if e["type"] in EVENT_CS and e["type"] not in GENERIC_VOTE
        ),
        None,
    )
    return {
        "steps": steps,
        "reached": MILESTONE_KEYS[reached] if reached is not None else None,
        "plenary_date": max(plenary) if plenary and reached is not None and reached >= 3 else None,
        "last_event": last,
        "unmapped": unmapped,
    }


def cz_roles(participants: list[dict], names: dict[int, str]) -> list[dict]:
    """Česká role v proceduře, každý poslanec jednou (nejvyšší role)."""
    best: dict[int, str] = {}
    for p in participants:
        role = CZ_ROLES.get(p.get("role"))
        if role and (p["mep_id"] not in best or ROLE_ORDER.index(role) < ROLE_ORDER.index(best[p["mep_id"]])):
            best[p["mep_id"]] = role
    rows = [{"mep_id": m, "name": names.get(m), "role": r, "role_cs": CZ_ROLE_CS[r]} for m, r in best.items()]
    return sorted(rows, key=lambda r: (ROLE_ORDER.index(r["role"]), r["name"] or "", r["mep_id"]))


def vote_links(votes: list[dict]) -> dict[str, dict]:
    """{číslo procedury (2023/0436(COD)): poslední závěrečné hlasování {vote_id, vote_date, status}} z dat HowTheyVote."""
    out: dict[str, dict] = {}
    for v in votes:
        ref = (v.get("procedure") or {}).get("reference")
        if ref and is_final(v) and (ref not in out or (v["date"], v["id"]) > (out[ref]["vote_date"], out[ref]["vote_id"])):
            out[ref] = {"vote_id": v["id"], "vote_date": v["date"], "status": v.get("result")}
    return out


def session_view(agenda: dict | None, own_work: dict | None, names: dict[int, str], labels: dict[str, str]) -> dict | None:
    """Nejbližší zasedání: body programu s fází, procedurou, výborem, kategorií a českou stopou."""
    nxt = (agenda or {}).get("next")
    if not nxt:
        return None
    docs = (agenda or {}).get("docs") or {}
    roles = cz_roles_by_doc(own_work)
    items = []
    for it in nxt["items"]:
        meta = next((docs[d] for d in it["docs"] if d in docs), {})
        pid = meta.get("procedure")
        label = labels.get(pid) if pid else None
        cz = [
            {"mep_id": r["mep_id"], "name": names.get(r["mep_id"]), "role": r["role"], "role_cs": CZ_ROLE_CS[r["role"]]}
            for d in it["docs"]
            for r in roles.get(doc_key(d), [])
        ]
        items.append(
            {
                "id": it["id"],
                "date": it["date"],
                "order": it["order"],
                "title_cs": it["title_cs"],
                "title_en": it["title_en"],
                "docs": it["docs"],
                "legislative": it["legislative"],
                "stage": it.get("stage"),
                "stage_cs": STAGE_CS.get(it.get("stage")) if it.get("stage") else None,
                "procedure": {
                    "id": pid,
                    "label": label,
                    "type": process_type(label),
                    "url": OEIL_URL.format(label=label) if label else None,
                }
                if pid
                else None,
                "committee": committee_info(meta.get("committee")),
                "cz": cz,
            }
        )
    return {"from": nxt["from"], "to": nxt["to"], "items": items, "fetched": (agenda or {}).get("fetched")}


def procedures_view(
    proposals: dict | None, votes: dict[str, dict], names: dict[int, str], session: dict | None, today: str
) -> tuple[list[dict], list[dict], int, list[str]]:
    """(rozpracované, odhlasované, počet procedur bez událostí, neznámé typy událostí). votes = vote_links()."""
    on_agenda = {i["procedure"]["id"]: i["date"] for i in (session or {}).get("items", []) if i.get("procedure")}
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=DONE_DAYS)).isoformat()
    active, done, missing, unmapped = [], [], 0, set()
    for p in (proposals or {}).get("items", []):
        if p.get("kind") != "procedure" or p.get("process_type") not in LEGISLATIVE:
            continue
        cz = cz_roles(p.get("participants") or [], names)
        if not cz:
            continue
        if "events" not in p:
            missing += 1
            continue
        tl = timeline(p["events"], p.get("process_type"))
        unmapped.update(tl["unmapped"])
        row = {
            "procedure": p["procedure"],
            "label": p.get("label"),
            "type": p.get("process_type"),
            "title_cs": (p.get("title") or {}).get("cs"),
            "title_en": (p.get("title") or {}).get("en"),
            "url": p.get("url"),
            "committee": committee_info(p.get("committee")),
            "cz": cz,
            "steps": tl["steps"],
            "reached": tl["reached"],
            "last_event": tl["last_event"],
            "next_vote": on_agenda.get(p["procedure"]),
        }
        if tl["reached"] in ("plenary", "closed"):
            if tl["plenary_date"] and tl["plenary_date"] >= since:
                done.append({**row, "plenary_date": tl["plenary_date"], "vote": votes.get(p.get("label"))})
        else:
            active.append(row)
    # nahoře procedury na programu nejbližšího zasedání, pak nejblíž hlasování, pak podle poslední události
    active.sort(
        key=lambda r: (
            r["next_vote"] is None,
            r["next_vote"] or "",
            -(MILESTONE_KEYS.index(r["reached"]) if r["reached"] else -1),
            -(int((r["last_event"] or {}).get("date", "0000-00-00").replace("-", ""))),
            r["procedure"],
        )
    )
    done.sort(key=lambda r: (r["plenary_date"], r["procedure"]), reverse=True)
    return active, done, missing, sorted(unmapped)


def build(data_dir: Path, today: str) -> dict:
    agenda = _read(data_dir / "agenda.json")
    own_work = _read(data_dir / "own_work.json")
    proposals = _read(data_dir / "proposals.json")
    state = _read(data_dir / "proposals_state.json") or {}
    meps = (_read(data_dir / "meps.json") or {}).get("meps", [])
    apply_name_overrides(meps, data_dir / "manual" / "overrides.json")  # jména s diakritikou jako jinde na webu
    names = {m["id"]: _name(m) for m in meps}
    labels = {pid: meta.get("label") for pid, meta in (state.get("procedures") or {}).items()}
    session = session_view(agenda, own_work, names, labels)
    votes = vote_links(load_votes(data_dir / "votes")[1]) if (data_dir / "votes" / "index.json").exists() else {}
    active, done, missing, unmapped = procedures_view(proposals, votes, names, session, today)
    return {
        "note": "Radar „Co se chystá“: program nejbližšího zasedání a legislativní procedury s českou stopou. "
        "Generuje scripts/radar.py z agenda.json, proposals.json a own_work.json.",
        "sources": [{"name": "EP Open Data API v2", "url": "https://data.europarl.europa.eu/api/v2", "license": "CC BY 4.0"}],
        "updated": (agenda or {}).get("fetched"),
        "session": session,
        "active": active,
        "done": done,
        "without_events": missing,
        "unmapped_events": unmapped,
        "categories": sorted({c for _, (_, c) in COMMITTEES.items() if c}),
    }


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    data_dir = Path(argv[0]) if argv else root / "data"
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    radar = build(data_dir, today)
    (data_dir / "radar.json").write_text(json.dumps(radar, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(
        f"radar: {len(radar['active'])} rozpracovaných, {len(radar['done'])} odhlasovaných, {radar['without_events']} bez událostí",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
