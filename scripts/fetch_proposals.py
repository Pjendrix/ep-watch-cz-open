"""Stáhne z EP Open Data API „vlastní práci“ českých poslanců v 10. období.

Zprávy (zpravodaj), stínové zprávy a stanoviska (z legislativních procedur), návrhy usnesení
a společné návrhy usnesení (signatáři) a otázky Komisi/Radě (písemné, přednostní, ústní).
Výsledky hlasování sem nepatří: ty k položkám přiřazuje compute_stats.py z HowTheyVote.

Výstup:
  data/proposals.json        položky, na kterých se podílel aspoň jeden český poslanec
  data/proposals_state.json  co už bylo staženo (ID, datum stažení) a vazby mezi dokumenty
                             (zpráva -> procedura, společný návrh -> nahrazené návrhy);
                             díky tomu týdenní běh stahuje jen nové položky

API neumí filtrovat podle poslance, takže se stahuje detail každé položky (s language=cs,
což zmenší odpověď z ~700 kB na jednotky kB). První běh je dlouhý (asi 14 000 dotazů, EP API
odpovídá u dokumentů pléna i desítky sekund). Stav se ukládá průběžně; --max-minutes a
--max-requests běh ukončí a příští běh naváže.

Použití:
    python scripts/fetch_proposals.py [--max-minutes 120] [--max-requests 2000] [--years 2024 2025 2026]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

from fetch_meps import EPClient, FormatError, first_item, require

TERM = 10
TERM_START = "2024-07-16"
DOC_URL = "https://www.europarl.europa.eu/doceo/document/{id}_EN.html"
OEIL_URL = "https://oeil.secure.europarl.europa.eu/oeil/en/procedure-file?reference={label}"
REFRESH_PROCEDURES_DAYS = 28
# Rozpracované procedury s českou účastí (radar „Co se chystá“) se obnovují častěji: fáze a události se mění týdně.
REFRESH_ACTIVE_DAYS = 7
# Událost, po které je procedura uzavřená (podpis nebo vyhlášení v Úředním věstníku); current_stage z API to neukazuje.
CLOSING_EVENTS = {"SIGNATURE", "PUBLICATION_OFFICIAL_JOURNAL"}

DOC_KINDS = {
    "def/ep-document-types/REPORT_PLENARY": "report",
    "def/ep-document-types/RESOLUTION_MOTION": "motion",
    "def/ep-document-types/RESOLUTION_MOTION_JOINT": "joint_motion",
}
QUESTION_KINDS = {
    "def/ep-document-types/QUESTION_WRITTEN": "question_written",
    "def/ep-document-types/QUESTION_WRITTEN_PRIORITY": "question_priority",
    "def/ep-document-types/QUESTION_ORAL": "question_oral",
}
PROCEDURE_ROLES = {"RAPPORTEUR", "RAPPORTEUR_SHADOW", "RAPPORTEUR_OPINION", "RAPPORTEUR_SHADOW_OPINION",
                   "RAPPORTEUR_CO"}


class Budget(Exception):
    """Vyčerpán počet dotazů na tento běh."""


def as_list(value) -> list:
    """API vrací u jediné hodnoty objekt nebo text místo seznamu; sjednotí na seznam."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def short(uri: str | None) -> str | None:
    return None if uri is None else str(uri).rsplit("/", 1)[-1]


def title_of(obj: dict, field: str = "title_dcterms") -> dict:
    t = obj.get(field) or {}
    return {"cs": t.get("cs"), "en": t.get("en")} if isinstance(t, dict) else {"cs": None, "en": None}


def person_ids(participation: dict) -> list[int]:
    return [int(short(p)) for p in as_list(participation.get("had_participant_person"))]


def cz_participants(work: dict, cz_ids: set[int], roles: set[str] | None = None) -> list[dict]:
    """Účast českých poslanců (ID, role, frakce, datum) z workHadParticipation / had_participation."""
    out = []
    parts = as_list(work.get("workHadParticipation") or work.get("had_participation"))
    for p in parts:
        if not isinstance(p, dict):
            raise FormatError(f"{work.get('identifier') or work.get('process_id')}: neočekávaná účast {p!r}")
        role = short(p.get("participation_role"))
        if roles is not None and role not in roles:
            continue
        if p.get("parliamentary_term") not in (None, f"org/ep-{TERM}"):
            continue
        for pid in person_ids(p):
            if pid in cz_ids:
                out.append({"mep_id": pid, "role": role, "group": short(p.get("politicalGroup")),
                            "in_name_of": short(p.get("participation_in_name_of")),
                            "date": (p.get("activity_date") or None)})
    return sorted(out, key=lambda x: (x["mep_id"], x["role"] or ""))


def count_persons(work: dict, role: str = "AUTHOR") -> int:
    return sum(len(person_ids(p)) for p in as_list(work.get("workHadParticipation"))
               if short(p.get("participation_role")) == role)


def parse_document(doc: dict, cz_ids: set[int]) -> tuple[dict, dict | None]:
    """Vrací (metadata do stavu, položka pro proposals.json nebo None)."""
    require(doc, ["identifier", "work_type"], f"plenary-documents/{doc.get('identifier')}")
    kind = DOC_KINDS.get(doc["work_type"])
    procs = [short(p) for p in as_list(doc.get("inverse_created_a_realization_of"))]
    meta = {
        "kind": kind,
        "label": doc.get("label"),
        "date": doc.get("document_date"),
        "procedure": procs[0] if procs else None,
        "derived_from": [short(x) for x in as_list(doc.get("is_derivative_of")) if "/doc/B-" in str(x)],
    }
    if kind is None:
        return meta, None
    roles = {"RAPPORTEUR", "RAPPORTEUR_CO"} if kind == "report" else {"AUTHOR"}
    parts = cz_participants(doc, cz_ids, roles)
    if not parts:
        return meta, None
    item = {
        "id": doc["identifier"], "kind": kind, "label": doc.get("label"), "date": doc.get("document_date"),
        "title": title_of(doc), "procedure": meta["procedure"], "derived_from": meta["derived_from"],
        "participants": parts, "signatories_total": count_persons(doc) if kind != "report" else None,
        "url": DOC_URL.format(id=doc["identifier"]),
    }
    return meta, item


def parse_procedure(proc: dict, cz_ids: set[int]) -> dict | None:
    require(proc, ["process_id"], f"procedures/{proc.get('process_id')}")
    parts = cz_participants(proc, cz_ids, PROCEDURE_ROLES)
    if not parts:
        return None
    label = proc.get("label")
    return {
        "id": f"proc-{proc['process_id']}", "kind": "procedure", "label": label,
        "procedure": proc["process_id"], "process_type": short(proc.get("process_type")),
        "title": title_of(proc, "process_title"), "participants": parts,
        "date": min((p["date"] for p in parts if p["date"]), default=None),
        "url": OEIL_URL.format(label=label) if label else None,
        # pro radar „Co se chystá“: odpovědný výbor a události procedury (typ a datum, jak je vrací API)
        "committee": lead_committee(proc),
        "events": procedure_events(proc),
    }


def lead_committee(proc: dict) -> str | None:
    """Odpovědný výbor (role COMMITTEE_LEAD); bez něj výbor zpravodaje (RAPPORTEUR). Jinak None."""
    parts = [p for p in as_list(proc.get("had_participation")) if isinstance(p, dict)]
    for role, field in (("COMMITTEE_LEAD", "had_participant_organization"), ("RAPPORTEUR", "participation_in_name_of")):
        for p in parts:
            if short(p.get("participation_role")) == role:
                orgs = [short(o) for o in as_list(p.get(field)) if o]
                if orgs:
                    return orgs[0]
    return None


def procedure_events(proc: dict) -> list[dict]:
    """Události procedury [{date, type}] seřazené podle data, bez duplicit (API je vrací i vícekrát)."""
    out = set()
    for e in as_list(proc.get("consists_of")):
        if not isinstance(e, dict):
            raise FormatError(f"procedures/{proc.get('process_id')}: neočekávaná událost {e!r}")
        if e.get("activity_date") and e.get("had_activity_type"):
            out.add((str(e["activity_date"])[:10], short(e["had_activity_type"])))
    return [{"date": d, "type": t} for d, t in sorted(out)]


def is_active(item: dict | None) -> bool:
    """Procedura s českou účastí, která ještě není uzavřená (nebo u ní ještě nemáme události)."""
    if not item:
        return False
    if "events" not in item:
        return True
    return not any(e["type"] in CLOSING_EVENTS for e in item["events"])


def question_label(identifier: str) -> str:
    """E-10-2026-000187 -> E-000187/2026 (označení, které používá web EP)."""
    parts = identifier.split("-")
    if len(parts) == 4:
        return f"{parts[0]}-{parts[3]}/{parts[2]}"
    return identifier


def parse_question(q: dict, cz_ids: set[int]) -> dict | None:
    require(q, ["identifier", "work_type"], f"parliamentary-questions/{q.get('identifier')}")
    kind = QUESTION_KINDS.get(q["work_type"])
    parts = cz_participants(q, cz_ids, {"AUTHOR"})
    if kind is None or not parts:
        return None
    answers = [a for a in as_list(q.get("inverse_answers_to")) if isinstance(a, dict)]
    addressees = [short(o) for p in as_list(q.get("workHadParticipation"))
                  if short(p.get("participation_role")) == "ADDRESSEE" for o in as_list(p.get("had_participant_organization"))]
    return {
        "id": q["identifier"], "kind": kind, "label": q.get("label") or question_label(q["identifier"]),
        "date": q.get("document_date"), "title": title_of(q), "participants": parts,
        "authors_total": count_persons(q), "addressee": addressees,
        "answer_date": min((a.get("document_date") for a in answers if a.get("document_date")), default=None),
        "url": DOC_URL.format(id=q["identifier"]),
    }


class Fetcher:
    def __init__(self, client: EPClient, cz_ids: set[int], state: dict, items: dict, max_requests: int, today: str,
                 save=None, deadline: float | None = None, log=None, voted: set[str] | None = None):
        self.client, self.cz_ids, self.state, self.items = client, cz_ids, state, items
        self.voted = voted or set()  # procedury (2023-0436), o kterých se hlasovalo podle HowTheyVote
        self.left, self.today, self.save = max_requests, today, save or (lambda: None)
        self.deadline, self.log = deadline, log or (lambda msg: None)
        self.done_since_save = 0
        self.fetched = 0

    def get(self, path: str, params: dict | None = None) -> dict:
        if self.left <= 0 or (self.deadline is not None and time.monotonic() > self.deadline):
            raise Budget()
        self.left -= 1
        return self.client.get(path, params)

    def detail(self, endpoint: str, item_id: str) -> dict:
        """Detail s českými texty (language=cs: malá odpověď, český název)."""
        return first_item(self.get(f"{endpoint}/{item_id}", {"language": "cs"}), f"{endpoint}/{item_id}")

    def english_title(self, endpoint: str, item: dict, field: str = "title_dcterms") -> None:
        """Když chybí český název, doplní anglický (jen u položek s českými poslanci)."""
        if item["title"].get("cs"):
            return
        key = item["procedure"] if endpoint == "procedures" else item["id"]
        en = first_item(self.get(f"{endpoint}/{key}", {"language": "en"}), f"{endpoint}/{key}")
        item["title"]["en"] = title_of(en, field).get("en")

    def checkpoint(self) -> None:
        self.done_since_save += 1
        self.fetched += 1
        if self.fetched % 100 == 0:
            self.log(f"staženo {self.fetched} položek, položek s Čechy {len(self.items)}")
        if self.done_since_save >= 50:
            self.save()
            self.done_since_save = 0

    def list_ids(self, endpoint: str, year: int, key: str = "identifier") -> list[str]:
        ids, offset = [], 0
        while True:
            payload = self.get(endpoint, {"year": year, "offset": offset, "limit": 500})
            require(payload, ["data"], f"GET /{endpoint}?year={year}")
            batch = payload["data"]
            for x in batch:
                require(x, [key], f"GET /{endpoint} položka")
                ids.append(x[key])
            if len(batch) < 500:
                return ids
            offset += 500

    def documents(self, years: list[int]) -> None:
        seen = self.state["documents"]
        for year in years:
            for doc_id in self.list_ids("plenary-documents", year):
                if f"-{TERM}-" not in doc_id or doc_id in seen:
                    continue
                doc = self.detail("plenary-documents", doc_id)
                meta, item = parse_document(doc, self.cz_ids)
                if item:
                    self.english_title("plenary-documents", item)
                    self.items[item["id"]] = item
                seen[doc_id] = {**meta, "fetched": self.today}
                self.checkpoint()

    def procedures(self, years: list[int]) -> None:
        seen = self.state["procedures"]
        ids = set()
        for year in years:
            ids.update(self.list_ids("procedures", year, key="process_id"))
        # Procedury, ze kterých vzešla zpráva 10. období (i ty starší, převzaté z 9. období).
        ids.update(m["procedure"] for m in self.state["documents"].values() if m.get("procedure"))
        day = dt.date.fromisoformat(self.today)
        stale = (day - dt.timedelta(days=REFRESH_PROCEDURES_DAYS)).isoformat()
        stale_active = (day - dt.timedelta(days=REFRESH_ACTIVE_DAYS)).isoformat()
        active = {i for i in ids if is_active(self.items.get(f"proc-{i}"))}
        # Procedury, o kterých se hlasovalo, potřebují český název (web ho ukazuje místo anglického z HowTheyVote).
        no_title = {i for i in self.voted if not seen.get(i, {}).get("title_cs")}
        ids |= no_title
        # Nejdřív nestažené, pak rozpracované české bez událostí, pak hlasované bez českého názvu, pak rozpracované
        # české a nakonec nejdéle nestahované (stínoví zpravodajové přibývají v průběhu procedury).
        order = sorted(ids, key=lambda i: (i in seen, not (i in active and "events" not in self.items.get(f"proc-{i}", {})),
                                           i not in no_title, i not in active, seen.get(i, {}).get("fetched", ""), i))
        for proc_id in order:
            limit = stale_active if proc_id in active else stale
            if (proc_id in seen and seen[proc_id]["fetched"] > limit and proc_id not in no_title
                    and "events" in self.items.get(f"proc-{proc_id}", {"events": 1})):
                continue
            proc = self.detail("procedures", proc_id)
            item = parse_procedure(proc, self.cz_ids)
            key = f"proc-{proc_id}"
            if item:
                self.english_title("procedures", item, "process_title")
                self.items[key] = item
            else:
                self.items.pop(key, None)
            seen[proc_id] = {"fetched": self.today, "label": proc.get("label"),
                             "title_cs": title_of(proc, "process_title").get("cs")}
            self.checkpoint()

    def questions(self, years: list[int]) -> None:
        seen = self.state["questions"]
        for year in years:
            for q_id in self.list_ids("parliamentary-questions", year):
                if f"-{TERM}-" not in q_id or q_id in seen:
                    continue
                self._question(q_id)
        # České otázky bez odpovědi se kontrolují znovu, jestli mezitím odpověď nepřišla.
        for item in [i for i in self.items.values() if i["kind"].startswith("question") and not i["answer_date"]]:
            if seen.get(item["id"], {}).get("fetched") != self.today:
                self._question(item["id"])

    def _question(self, q_id: str) -> None:
        q = self.detail("parliamentary-questions", q_id)
        item = parse_question(q, self.cz_ids)
        if item:
            self.english_title("parliamentary-questions", item)
            self.items[item["id"]] = item
        self.state["questions"][q_id] = {"fetched": self.today}
        self.checkpoint()


def voted_procedures(votes_dir: Path) -> set[str]:
    """Procedury z hlasování HowTheyVote (2023/0436(COD) -> 2023-0436); bez dat prázdná množina."""
    index = load(votes_dir / "index.json", None)
    out = set()
    for m in (index or {}).get("months", []):
        for v in load(votes_dir / f"{m['month']}.json", {"votes": []})["votes"]:
            ref = (v.get("procedure") or {}).get("reference")
            if ref and len(ref) >= 9 and ref[4] == "/":
                out.add(ref[:9].replace("/", "-"))
    return out


def load(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write(path: Path, obj) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    today = dt.datetime.now(dt.timezone.utc).date()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    p.add_argument("--years", type=int, nargs="+", default=list(range(2024, today.year + 1)))
    p.add_argument("--max-requests", type=int, default=100_000)
    p.add_argument("--max-minutes", type=float, default=None, help="po této době stav uložit a skončit")
    p.add_argument("--only", choices=["documents", "procedures", "questions"], nargs="+",
                   default=["documents", "procedures", "questions"])
    args = p.parse_args(argv)

    meps = json.loads((args.data_dir / "meps.json").read_text(encoding="utf-8"))["meps"]
    cz_ids = {m["id"] for m in meps}
    state_path, items_path = args.data_dir / "proposals_state.json", args.data_dir / "proposals.json"
    state = load(state_path, {"documents": {}, "procedures": {}, "questions": {}})
    # Jednorázově stažené české názvy (data/procedure_titles_cs.json): procedury s názvem se znovu nestahují kvůli názvu.
    for pid, meta in load(args.data_dir / "procedure_titles_cs.json", {"titles": {}})["titles"].items():
        if pid in state["procedures"] and not state["procedures"][pid].get("title_cs") and meta.get("title_cs"):
            state["procedures"][pid]["title_cs"] = meta["title_cs"]
    items = {i["id"]: i for i in load(items_path, {"items": []})["items"]}

    def save():
        state["updated"] = today.isoformat()
        write(state_path, state)
        write(items_path, {
            "source": {"name": "EP Open Data API v2", "url": "https://data.europarl.europa.eu/api/v2",
                       "license": "CC BY 4.0"},
            "term": TERM, "term_start": TERM_START,
            "items": sorted(items.values(), key=lambda i: (i.get("date") or "", i["id"])),
        })

    client = EPClient(cache_dir=root / ".cache" / "ep" / "corporate-bodies", min_interval=0.8)
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None
    fetcher = Fetcher(client, cz_ids, state, items, args.max_requests, today.isoformat(), save, deadline,
                      log=lambda msg: print(msg, file=sys.stderr, flush=True), voted=voted_procedures(args.data_dir / "votes"))
    complete = True
    try:
        for part in args.only:
            getattr(fetcher, part)(args.years)
    except Budget:
        complete = False
        print("vyčerpán čas nebo počet dotazů pro tento běh, příští běh naváže", file=sys.stderr)
    except FormatError as e:
        save()
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    state["complete"] = complete
    save()
    kinds = {}
    for i in items.values():
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    print(f"položky s českými poslanci: {kinds}; staženo dokumentů {len(state['documents'])}, "
          f"procedur {len(state['procedures'])}, otázek {len(state['questions'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
