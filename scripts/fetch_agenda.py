"""Kalendář plenárních zasedání a program hlasování příštího zasedání z EP Open Data API v2 (data/agenda.json).

- GET /meetings?year=RRRR: plenární dny (MTG-PL-RRRR-MM-DD), i dopředu. Dny po sobě (mezera nejvýš 2 dny) = jedno zasedání.
- GET /meetings/{id}/foreseen-activities: plánovaný program dne. Bereme jen body typu PLENARY_VOTE (hlasování):
  český název, pořadí v programu, fáze procedury (occured_at_stage) a dokumenty, ke kterým se váže
  (A-10-… zpráva výboru, B-10-… návrh usnesení, C-10-… / C-9-… legislativní návrh Komise).
- GET /plenary-documents/{A-…}: procedura a odpovědný výbor zprávy (pro radar „Co se chystá“). Výsledek se drží
  v souboru (pole docs), takže každá zpráva se dotazuje jen jednou.

Program je návrh EP a může se změnit; web to tak i píše. Nic se nedopočítává: co API nemá, je null.
Soubor se změní, jen když se změní obsah (datum stažení se pak nepřepisuje), aby denní běh necommitoval zbytečně.
Limit EP API (500 dotazů / 5 min) se nepřiblíží: jde o jednotky dotazů.

Použití:
    python scripts/fetch_agenda.py [--today RRRR-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from fetch_meps import EPClient, FormatError, require

VOTE_TYPE = "def/ep-activities/PLENARY_VOTE"
SITTING_RE = re.compile(r"^MTG-PL-(\d{4}-\d{2}-\d{2})$")
DOC_RE = re.compile(r"(?:^|/)([A-Z]-\d{1,2}-\d{4}-\d{4})$")


def sittings_for_year(client: EPClient, year: int) -> list[str]:
    """Plenární dny daného roku (RRRR-MM-DD), seřazené."""
    payload = client.get("meetings", {"year": year, "offset": 0, "limit": 500})
    require(payload, ["data"], f"GET /meetings?year={year}")
    days = set()
    for m in payload["data"]:
        require(m, ["activity_id"], "meeting")
        hit = SITTING_RE.match(m["activity_id"])
        if hit:
            days.add(hit[1])
    return sorted(days)


def group_sessions(days: list[str], max_gap: int = 2) -> list[list[str]]:
    """Plenární dny po sobě (mezera nejvýš max_gap dny) = jedno zasedání."""
    out: list[list[str]] = []
    for d in sorted(days):
        if out and (dt.date.fromisoformat(d) - dt.date.fromisoformat(out[-1][-1])).days <= max_gap:
            out[-1].append(d)
        else:
            out.append([d])
    return out


def next_session(days: list[str], today: str) -> list[str] | None:
    """Nejbližší zasedání, které ještě neskončilo (probíhající nebo budoucí)."""
    return next((s for s in group_sessions(days) if s[-1] >= today), None)


def vote_items(payload: dict, day: str) -> list[dict]:
    """Hlasovací body z programu dne. Validuje pole, při změně formátu skončí čitelnou chybou."""
    require(payload, ["data"], f"foreseen-activities {day}")
    items = []
    for a in payload["data"]:
        # jen hlasovací body; ostatní části programu (MEETING_PART, rozpravy) datum mít nemusí
        if a.get("had_activity_type") != VOTE_TYPE:
            continue
        require(a, ["activity_id", "activity_date"], f"foreseen-activities {day}")
        label = a.get("activity_label") or {}
        if not isinstance(label, dict):
            raise FormatError(f"{a['activity_id']}: activity_label není slovník jazyků")
        docs = []
        for ref in a.get("based_on_a_realization_of") or []:
            hit = DOC_RE.search(str(ref))
            if hit and hit[1] not in docs:
                docs.append(hit[1])
        order = a.get("activity_order")
        items.append(
            {
                "id": a["activity_id"],
                "date": str(a["activity_date"])[:10],
                "order": float(order) if isinstance(order, (int, float, str)) and str(order).replace(".", "", 1).isdigit() else None,
                "title_cs": label.get("cs"),
                "title_en": label.get("en"),
                "docs": docs,
                "legislative": any(d.startswith("C-") for d in docs),
                "stage": _short(a.get("occured_at_stage")),
            }
        )
    items.sort(key=lambda x: (x["date"], x["order"] if x["order"] is not None else 1e9, x["id"]))
    return items


def _short(uri) -> str | None:
    return str(uri).rsplit("/", 1)[-1] if uri else None


def report_meta(client: EPClient, doc_id: str) -> dict:
    """Procedura a odpovědný výbor zprávy A-…: {procedure, committee}; co API nemá, je None."""
    d = client.get(f"plenary-documents/{doc_id}", {"language": "cs"})
    require(d, ["data"], f"plenary-documents/{doc_id}")
    if not d["data"]:
        return {"procedure": None, "committee": None}
    doc = d["data"][0]
    procs = doc.get("inverse_created_a_realization_of") or []
    procs = procs if isinstance(procs, list) else [procs]
    creators = doc.get("creator") or []
    creators = creators if isinstance(creators, list) else [creators]
    orgs = [_short(c) for c in creators if str(c).startswith("org/")]
    return {"procedure": _short(procs[0]) if procs else None, "committee": orgs[0] if orgs else None}


def build(client: EPClient, today: str, known_docs: dict | None = None) -> dict:
    year = int(today[:4])
    days = sittings_for_year(client, year)
    if today[5:7] in ("11", "12"):  # na konci roku i kalendář dalšího roku
        days += sittings_for_year(client, year + 1)
    if not days:
        raise FormatError(f"EP API nevrátilo žádné plenární dny pro rok {year}")
    session = next_session(days, today)
    items: list[dict] = []
    if session:
        for d in session:
            items += vote_items(client.get(f"meetings/MTG-PL-{d}/foreseen-activities"), d)
    docs = {}
    for it in items:
        for d in it["docs"]:
            if d.startswith("A-") and d not in docs:
                docs[d] = (known_docs or {}).get(d) or report_meta(client, d)
    return {
        "note": "Plenární dny a program hlasování nejbližšího zasedání (návrh programu EP, může se změnit). Generuje scripts/fetch_agenda.py.",
        "source": {"name": "EP Open Data API v2", "url": "https://data.europarl.europa.eu/api/v2/meetings", "license": "CC BY 4.0"},
        "sittings": sorted(set(days)),
        "next": {"from": session[0], "to": session[-1], "days": session, "items": items} if session else None,
        "docs": dict(sorted(docs.items())),
    }


def write_if_changed(path: Path, doc: dict, today: str) -> bool:
    """Zapíše soubor jen při změně obsahu; datum stažení se nastaví jen tehdy (žádné denní commity bez změny)."""
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if old and {k: v for k, v in old.items() if k != "fetched"} == doc:
        return False
    path.write_text(json.dumps({**doc, "fetched": today}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=root / "data" / "agenda.json")
    p.add_argument("--today", default=dt.datetime.now(dt.timezone.utc).date().isoformat())
    args = p.parse_args(argv)
    try:
        old = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
        doc = build(EPClient(), args.today, old.get("docs"))
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    prev = (old.get("next") or {}) if old else {}
    nxt = doc["next"]
    if nxt and not nxt["items"] and prev.get("from") == nxt["from"] and prev.get("items"):
        # EP API občas vrátí program bez hlasovacích bodů; dřívější úplný program stejného zasedání se nepřepíše
        print(
            f"CHYBA: API vrátilo program zasedání {nxt['from']} bez hlasování, předchozí stažení mělo "
            f"{len(prev['items'])} bodů; soubor se nemění",
            file=sys.stderr,
        )
        return 3
    changed = write_if_changed(args.out, doc, args.today)
    nxt = doc["next"]
    print(
        f"program: {'beze změny' if not changed else 'uloženo'}; příští zasedání "
        f"{(nxt['from'] + ' – ' + nxt['to'] + ', ' + str(len(nxt['items'])) + ' hlasovacích bodů') if nxt else 'neznámé'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
