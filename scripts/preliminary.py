"""Předběžné výsledky jmenovitých hlasování po zasedání (zadání 24. 10. 2026, část C).

Zdroj: EP Open Data API, GET /meetings/MTG-PL-{datum}/decisions (rozhodnutí 24. 10. 2026: XML na europarl.europa.eu/doceo
je za ochranou proti botům, API vrací stejná data i s ID poslanců). HowTheyVote vydává export s několikadenním
zpožděním; do té doby web ukazuje na úvodu, jak čeští poslanci hlasovali, se štítkem „předběžné“.

Pravidla:
- Jen jmenovitá hlasování (VOTE_ELECTRONIC_ROLLCALL) se seznamy hlasujících. Hlas = zaznamenaný hlas (had_voter_*),
  stejně jako HowTheyVote; opravy hlasu (had_voter_intended_*) se jen uvádějí vedle, výsledek nemění.
- Čeští poslanci podle ID z data/meps.json, jen v den hlasování v mandátu. V mandátu a v žádném seznamu = nehlasoval.
  Frakce a strana k datu hlasování.
- Hlavní hlasování = jmenovité hlasování o celém textu: bez čísla pozměňovacího návrhu či odstavce (decisionAboutId),
  o prozatímní dohodě s Radou, nebo o návrhu na zamítnutí návrhu Komise. Propadlá (LAPSED) se nepočítají. Pravidlo ověřené proti is_main z HowTheyVote (test).
- Výběr bodů na úvod stejným pravidlem jako stránka Zasedání (session_page.session_view → picks), spárovaný
  s hlavními hlasováními podle čísla dokumentu (A10-…, B10-…, C10-…).
- Den, který už je v datech HowTheyVote (data/votes), se maže a na webu se neukazuje. Do statistik nic nevstupuje.
"""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path

from compute_stats import FormatError, require  # bez requests: modul importuje i sestavení webu na Vercelu (portal.py)

API_URL = "https://data.europarl.europa.eu/api/v2/meetings/MTG-PL-{day}/decisions"
ROLLCALL = "def/ep-decision-methods/VOTE_ELECTRONIC_ROLLCALL"
POSITIONS = ("FOR", "AGAINST", "ABSTENTION")
VOTER_KEYS = {"FOR": "had_voter_favor", "AGAINST": "had_voter_against", "ABSTENTION": "had_voter_abstention"}
INTENDED_KEYS = {"FOR": "had_voter_intended_favor", "AGAINST": "had_voter_intended_against", "ABSTENTION": "had_voter_intended_abstention"}
COUNT_KEYS = {"FOR": "number_of_votes_favor", "AGAINST": "number_of_votes_against", "ABSTENTION": "number_of_votes_abstention"}
RESULTS = {"ADOPTED", "REJECTED"}
REQUIRED = ["decision_method"]
REQUIRED_ROLLCALL = ["activity_date", "notation_votingId", "decision_outcome", "activity_order"]
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
DOC_LABEL_RE = re.compile(r"\b((?:RC-)?[ABC])(\d+)-(\d{4})/(\d{4})\b")
AGENDA_DOC_RE = re.compile(r"(RC-[AB]|[ABC])-(\d+)-(\d{4})-(\d{4})")
TAG_RE = re.compile(r"<[^>]+>")
DAY_FILE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.json")


def source_url(day: str) -> str:
    return API_URL.format(day=day)


def _person_id(uri: str, where: str) -> int:
    m = re.fullmatch(r"person/(\d+)", uri or "")
    if not m:
        raise FormatError(f"{where}: neočekávaný identifikátor poslance {uri!r}")
    return int(m[1])


def _text(labels: dict | None) -> str | None:
    if not labels:
        return None
    s = labels.get("cs") or labels.get("en") or labels.get("mul")
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub("", s))).strip() if s else None


def doc_refs(text: str | None) -> list[str]:
    """Čísla dokumentů z popisku hlasování ve tvaru HowTheyVote: A10-0276/2026, RC-B10-0476/2026, C10-0258/2026."""
    return list(dict.fromkeys(f"{m[1]}{m[2]}-{m[3]}/{m[4]}" for m in DOC_LABEL_RE.finditer(text or "")))


def agenda_ref(doc: str) -> str | None:
    """Číslo dokumentu z programu (A-10-2026-0265, C-10-2025-0324) ve tvaru z popisku hlasování."""
    m = AGENDA_DOC_RE.fullmatch(doc)
    return f"{m[1]}{m[2]}-{m[4]}/{m[3]}" if m else None


def is_main(item: dict) -> bool:
    """Hlasování o celém textu (viz docstring modulu). Vstup je položka z parse_decisions."""
    return item["result"] in RESULTS and (item["about"] is None or item["agreement"] or item["rejection"])


def parse_decisions(payload: dict, day: str) -> list[dict]:
    """Jmenovitá hlasování dne z odpovědi /meetings/{id}/decisions. Při změně formátu FormatError."""
    if not DAY_RE.fullmatch(day):
        raise FormatError(f"neplatné datum {day!r}")
    require(payload, ["data"], f"decisions {day}")
    if not isinstance(payload["data"], list):
        raise FormatError(f"decisions {day}: 'data' není seznam")
    out = []
    for raw in payload["data"]:
        where = f"decisions {day} {raw.get('id', '?') if isinstance(raw, dict) else '?'}"
        require(raw, REQUIRED, where)
        if raw["decision_method"] != ROLLCALL:
            continue
        require(raw, REQUIRED_ROLLCALL, where)
        if raw["activity_date"] != day:
            raise FormatError(f"{where}: datum {raw['activity_date']} nepatří ke dni {day}")
        result = raw["decision_outcome"].rsplit("/", 1)[-1]
        voters = {pos: raw.get(VOTER_KEYS[pos]) or [] for pos in POSITIONS}
        if result == "LAPSED" or not any(voters.values()):
            continue  # propadlé hlasování, nikdo nehlasoval
        if result not in RESULTS:
            raise FormatError(f"{where}: neznámý výsledek {raw['decision_outcome']!r}")
        counts, positions = {}, {}
        for pos in POSITIONS:
            ids = [_person_id(u, where) for u in voters[pos]]
            n = raw.get(COUNT_KEYS[pos])
            if n is not None and int(n) != len(ids):
                raise FormatError(f"{where}: {COUNT_KEYS[pos]}={n}, ale seznam {VOTER_KEYS[pos]} má {len(ids)} jmen")
            counts[pos] = len(ids)
            for i in ids:
                if i in positions:
                    raise FormatError(f"{where}: poslanec {i} je ve dvou seznamech hlasů")
                positions[i] = pos
        intended = {}
        for pos in POSITIONS:
            for u in raw.get(INTENDED_KEYS[pos]) or []:
                intended[_person_id(u, where)] = pos
        label = _text(raw.get("activity_label"))
        heading = _text(raw.get("headingLabel"))
        about = raw.get("decisionAboutId")
        label_en = ((raw.get("activity_label") or {}).get("en") or "").lower()
        heading_en = ((raw.get("headingLabel") or {}).get("en") or "").lower()
        try:
            order = float(raw["activity_order"])
        except (TypeError, ValueError) as e:
            raise FormatError(f"{where}: activity_order {raw['activity_order']!r} není číslo") from e
        out.append(
            {
                "id": int(raw["notation_votingId"]),
                "time": raw.get("activity_start_date"),
                "order": order,
                "label": label,
                "heading": heading,
                "about": about.strip() if isinstance(about, str) and about.strip() else None,
                "agreement": "provisional agreement" in heading_en,
                "rejection": "proposal to reject" in heading_en or "proposal for rejection" in label_en,
                "refs": doc_refs(f"{(raw.get('activity_label') or {}).get('en') or ''} {(raw.get('headingLabel') or {}).get('en') or ''}"),
                "result": result,
                "counts": counts,
                "positions": positions,
                "intended": intended,
            }
        )
    out.sort(key=lambda v: (v["time"] or "", v["id"]))
    return out


def current(items: list[dict], day: str) -> dict | None:
    return next((x for x in items if x["start"] <= day and (x["end"] is None or day <= x["end"])), None)


def cz_rows(vote: dict, meps: list[dict], day: str, ep_to_code: dict[str, str]) -> list[list]:
    """[member_id, hlas, frakce, strana_org_id] pro české poslance v mandátu k danému dni (hlas FOR/AGAINST/ABSTENTION/DID_NOT_VOTE)."""
    rows = []
    for m in meps:
        if not current(m["mandates"], day):
            continue
        g, p = current(m["groups"], day), current(m["parties"], day)
        code = ep_to_code.get(g["code"], g["code"]) if g else None
        rows.append([m["id"], vote["positions"].get(m["id"], "DID_NOT_VOTE"), code, int(p["org_id"]) if p else None])
    return rows


def day_file(day: str, votes: list[dict], meps: list[dict], ep_to_code: dict[str, str], fetched: str) -> dict:
    """Obsah data/preliminary/{den}.json: jen jmenovitá hlasování dne, počty pro celý EP a hlasy Čechů podle ID."""
    cz_ids = {m["id"] for m in meps}
    return {
        "note": "Předběžné výsledky z EP Open Data API, ještě neověřené exportem HowTheyVote. Do statistik se nezapočítávají.",
        "date": day,
        "source": source_url(day),
        "fetched": fetched,
        "votes": [
            {
                "id": v["id"],
                "time": v["time"],
                "label": v["label"],
                "heading": v["heading"],
                "refs": v["refs"],
                "main": is_main(v),
                "result": v["result"],
                "counts": {k.lower(): v["counts"][k] for k in POSITIONS},
                "cz": cz_rows(v, meps, day, ep_to_code),
                "corrections": {str(i): p for i, p in sorted(v["intended"].items()) if i in cz_ids},
            }
            for v in votes
        ],
    }


def htv_last_day(votes_dir: Path) -> str | None:
    """Poslední den s hlasováním v datech HowTheyVote (data/votes); bez dat None."""
    index = votes_dir / "index.json"
    if not index.exists():
        return None
    months = [m["month"] for m in json.loads(index.read_text(encoding="utf-8")).get("months", [])]
    if not months:
        return None
    last = json.loads((votes_dir / f"{max(months)}.json").read_text(encoding="utf-8"))
    return max((v["date"] for v in last.get("votes", [])), default=None)


def pending_days(prelim_dir: Path, covered: str | None) -> list[str]:
    """Dny s předběžnými daty, která HowTheyVote ještě nemá (novější než covered), vzestupně."""
    if not prelim_dir.exists():
        return []
    days = sorted(p.stem for p in prelim_dir.iterdir() if DAY_FILE_RE.fullmatch(p.name))
    return [d for d in days if covered is None or d > covered]


def stale_files(prelim_dir: Path, covered: str | None) -> list[Path]:
    """Soubory dnů, které už HowTheyVote má (k smazání)."""
    if not prelim_dir.exists() or covered is None:
        return []
    return sorted(p for p in prelim_dir.iterdir() if DAY_FILE_RE.fullmatch(p.name) and p.stem <= covered)


def check_day(data: dict) -> None:
    """Ověří strukturu souboru data/preliminary/{den}.json (check_data, sestavení webu)."""
    require(data, ["date", "source", "fetched", "votes"], "preliminary")
    for v in data["votes"]:
        require(v, ["id", "label", "refs", "main", "result", "counts", "cz", "corrections"], f"preliminary {data['date']}")
        if v["result"] not in RESULTS:
            raise FormatError(f"preliminary {data['date']} {v['id']}: neznámý výsledek {v['result']!r}")
        for row in v["cz"]:
            if len(row) != 4 or row[1] not in (*POSITIONS, "DID_NOT_VOTE"):
                raise FormatError(f"preliminary {data['date']} {v['id']}: neplatný řádek {row!r}")


# --- Blok na úvodu ------------------------------------------------------------------------------------------------

POS_ORDER = ("FOR", "AGAINST", "ABSTENTION", "DID_NOT_VOTE")
POS_LABEL = {"FOR": "pro", "AGAINST": "proti", "ABSTENTION": "zdrželo se", "DID_NOT_VOTE": "nehlasovalo"}
FIX_LABEL = {"FOR": "pro", "AGAINST": "proti", "ABSTENTION": "zdržet se"}  # opravy hlasu ohlášené po hlasování
RESULT_LABEL = {"ADOPTED": "přijato", "REJECTED": "zamítnuto"}
HTV_VOTES = "https://howtheyvote.eu/votes"


def cz_summary(v: dict) -> dict[str, int]:
    return {p: sum(r[1] == p for r in v["cz"]) for p in POS_ORDER}


def home_items(days: list[dict], radar: dict | None, picks: list[str]) -> tuple[list[dict], list[dict]]:
    """(hlavní body podle výběru Zasedání s jejich hlasováními, ostatní hlavní hlasování). Pořadí bodů = pořadí výběru."""
    agenda = {it["id"]: it for it in ((radar or {}).get("session") or {}).get("items", [])}
    main = [dict(v, date=d["date"]) for d in days for v in d["votes"] if v["main"]]
    used, picked = set(), []
    for pid in picks:
        it = agenda.get(pid)
        if not it:
            continue
        refs = {r for r in (agenda_ref(x) for x in it.get("docs") or []) if r}
        hits = [v for v in main if refs & set(v["refs"]) and v["id"] not in used]
        if hits:
            used.update(v["id"] for v in hits)
            picked.append({"title": it.get("title_cs") or it.get("title_en"), "votes": hits})
    titles = {r: it.get("title_cs") for it in agenda.values() for r in (agenda_ref(x) for x in it.get("docs") or []) if r}
    rest = [dict(v, title=next((titles[r] for r in v["refs"] if titles.get(r)), None)) for v in main if v["id"] not in used]
    return picked, rest
