"""Stáhne pozměňovací návrhy (PN) v 10. období: ve výborech z DOCX registru EP, v plénu z EP Open Data API.

Výstup:
  data/amendments_state.json  co už bylo staženo: u každého dokumentu PN ve výborech datum, výbory, procedura a všichni
                              autoři s počty (díky tomu nový poslanec nevyžaduje nové stahování), u zpráv A10 jejich PN
  data/amendments.json        počty po českých poslancích (amendments.summarize), jen v době mandátu

Postup (podrobně docs/SPIKE_POZMENOVACI_NAVRHY.md):
1. Seznam dokumentů PN: /documents?work-type=AMENDMENT_LIST&year=… po 10 (větší stránky EP API shazují). Uzavřené roky
   se vypisují jen jednou, aktuální a předchozí rok při každém běhu.
2. Nové dokumenty výborů ({VÝBOR}-AM-číslo): DOCX z registru EP, z něj jen značky šablony (amendments.parse_committee_docx).
   Chybějící anglická verze (404) se zkusí v příštím běhu.
3. Zprávy A10 (z data/proposals_state.json): plenary-documents/{id}?language=cs → PN s autory v titulku. Zprávy z posledních
   REFRESH_REPORT_DAYS dní se stahují znovu (PN přibývají až do hlasování v plénu).
Stav se ukládá průběžně; --max-minutes běh ukončí a příští běh naváže.

Použití:
    python scripts/fetch_amendments.py [--max-minutes 60] [--cache-dir DIR]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

from amendments import COMMITTEE_DOC, DOCX_URL, FormatError, classify_plenary, docx_text, parse_committee_docx, summarize
from fetch_meps import EPClient, first_item, require

TERM_START = "2024-07-16"
FIRST_YEAR = 2024
PAGE = 10  # EP API: stránky nad ~10 položek padají na 500 (OutOfMemory)
REFRESH_REPORT_DAYS = 120
DOCX_INTERVAL = 0.5
SAVE_EVERY = 25
SOURCE = {
    "committee": {
        "name": "EP Open Data API v2 (seznam dokumentů) + DOCX z registru EP (autoři ze značek šablony)",
        "url": "https://data.europarl.europa.eu/api/v2/documents?work-type=AMENDMENT_LIST",
        "license": "CC BY 4.0",
    },
    "plenary": {
        "name": "EP Open Data API v2, plenary-documents (PN ke zprávám A10)",
        "url": "https://data.europarl.europa.eu/api/v2/plenary-documents",
        "license": "CC BY 4.0",
    },
}


class Budget(Exception):
    """Vypršel čas na tento běh."""


class Fetcher:
    def __init__(self, client: EPClient, state: dict, state_path: Path, deadline: float | None, cache_dir: Path | None, log=print):
        self.client, self.state, self.state_path, self.deadline, self.cache_dir, self.log = (
            client,
            state,
            state_path,
            deadline,
            cache_dir,
            log,
        )
        self.session = requests.Session()
        self._last_docx = 0.0
        self.changed = 0

    def check_budget(self) -> None:
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise Budget()

    def save(self) -> None:
        self.state["updated"] = dt.date.today().isoformat()
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    def touched(self) -> None:
        self.changed += 1
        if self.changed % SAVE_EVERY == 0:
            self.save()

    # 1. seznam dokumentů
    def list_year(self, year: int) -> list[str]:
        """Všechna ID dokumentů PN roku. Rozpracovaný výpis (vypršel čas) je ve stavu a příští běh na něj naváže."""
        part = self.state.setdefault("listing", {}).setdefault(str(year), {"offset": 0, "ids": []})
        while True:
            self.check_budget()
            payload = self.client.get("documents", {"work-type": "AMENDMENT_LIST", "year": year, "offset": part["offset"], "limit": PAGE})
            require(payload, ["data"], f"GET /documents?work-type=AMENDMENT_LIST&year={year}")
            batch = payload["data"]
            for x in batch:
                require(x, ["identifier"], "GET /documents položka")
                part["ids"].append(x["identifier"])
            part["offset"] += PAGE
            self.touched()
            if len(batch) < PAGE:
                return self.state["listing"].pop(str(year))["ids"]

    def listing(self, today: dt.date) -> list[str]:
        """Vypíše neuzavřené roky a vrátí všechna dosud vypsaná ID (i z uzavřených let, kde se DOCX nemusely stihnout)."""
        done = set(self.state.setdefault("years_complete", []))
        listed = set(self.state.setdefault("listed", []))
        for year in range(FIRST_YEAR, today.year + 1):
            if year in done:
                continue
            got = self.list_year(year)
            self.log(f"{year}: {len(got)} dokumentů PN")
            listed.update(got)
            self.state["listed"] = sorted(listed)
            if year < today.year - 1 or (year == today.year - 1 and today.month > 1):
                done.add(year)  # loňské dokumenty (s rokem v ID) se dovypisují jen v lednu
            self.state["years_complete"] = sorted(done)
        return self.state["listed"]

    # 2. výborové PN z DOCX
    def docx(self, doc_id: str) -> bytes | None:
        cached = self.cache_dir / f"{doc_id}_en.docx" if self.cache_dir else None
        if cached and cached.exists():
            return cached.read_bytes()
        wait = self._last_docx + DOCX_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_docx = time.monotonic()
        for attempt in range(4):
            try:
                r = self.session.get(DOCX_URL.format(id=doc_id, lang="en"), timeout=120)
            except requests.RequestException:
                time.sleep(2 ** (attempt + 1))
                continue
            if r.status_code == 404:
                return None
            if r.status_code >= 500:
                time.sleep(2 ** (attempt + 1))
                continue
            r.raise_for_status()
            if not r.content.startswith(b"PK"):
                raise FormatError(f"{doc_id}: odpověď není DOCX ({r.headers.get('content-type')})")
            if cached:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(r.content)
            return r.content
        raise RuntimeError(f"{doc_id}: registr EP opakovaně neodpovídá")

    def committee(self, ids: list[str]) -> None:
        com = self.state.setdefault("committee", {})
        todo = [i for i in ids if COMMITTEE_DOC.match(i) and com.get(i, {}).get("kind") in (None, "missing")]
        self.log(f"výborové PN: {len(todo)} dokumentů ke stažení")
        for doc_id in todo:
            self.check_budget()
            data = self.docx(doc_id)
            if data is None:
                com[doc_id] = {"kind": "missing", "checked": dt.date.today().isoformat()}
            else:
                com[doc_id] = parse_committee_docx(docx_text(data), doc_id)
            self.touched()

    # 3. plenární PN ke zprávám A10
    def plenary(self, today: dt.date, proposals_state: dict) -> None:
        plen = self.state.setdefault("plenary", {})
        reports = {k: v for k, v in proposals_state.get("documents", {}).items() if k.startswith("A-10-") and v.get("kind") == "report"}
        fresh = (today - dt.timedelta(days=REFRESH_REPORT_DAYS)).isoformat()
        todo = [k for k, v in sorted(reports.items()) if k not in plen or (v.get("date") or "") >= fresh]
        self.log(f"plenární PN: {len(todo)} zpráv ke stažení")
        for rep in todo:
            self.check_budget()
            d = first_item(self.client.get(f"plenary-documents/{rep}", {"language": "cs"}), f"plenary-documents/{rep}")
            ams = []
            for a in d.get("inverse_foresees_change_of") or []:
                if not str(a.get("work_type", "")).endswith("AMENDMENT_LIST"):
                    continue
                title = next(iter((a.get("title_dcterms") or {}).values()), "")
                kind, people, group = classify_plenary(title)
                b, e = a.get("itemNumberBegin"), a.get("itemNumberEnd")
                ams.append(
                    {
                        "id": a.get("identifier"),
                        "date": a.get("document_date"),
                        "n": e - b + 1 if isinstance(b, int) and isinstance(e, int) and e >= b else 1,
                        "kind": kind,
                        **({"people": people} if kind == "members" else {}),
                        **({"group": group} if group else {}),
                    }
                )
            plen[rep] = {"fetched": today.isoformat(), "amendments": sorted(ams, key=lambda x: x["id"] or "")}
            self.touched()


def build(state: dict, meps: list[dict]) -> dict:
    return {"source": SOURCE, "term_start": TERM_START, "updated": state.get("updated"), **summarize(state, meps)}


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    p.add_argument("--max-minutes", type=float, default=None, help="po tolika minutách stahování skončí (stav zůstane, příští běh naváže)")
    p.add_argument("--cache-dir", type=Path, default=None, help="adresář pro stažené DOCX (jen lokálně, v CI se nepoužívá)")
    p.add_argument("--summary-only", action="store_true", help="nic nestahuje, jen přepočítá data/amendments.json ze stavu")
    args = p.parse_args(argv)
    state_path, out_path = args.data_dir / "amendments_state.json", args.data_dir / "amendments.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    meps = json.loads((args.data_dir / "meps.json").read_text(encoding="utf-8"))["meps"]
    log = lambda m: print(m, file=sys.stderr, flush=True)  # noqa: E731
    status = 0
    if not args.summary_only:
        deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None
        f = Fetcher(EPClient(min_interval=0.8), state, state_path, deadline, args.cache_dir, log)
        today = dt.date.today()
        proposals_state = json.loads((args.data_dir / "proposals_state.json").read_text(encoding="utf-8"))
        try:
            f.committee(f.listing(today))
            f.plenary(today, proposals_state)
            state["complete"] = True
        except Budget:
            log("vypršel čas, příští běh naváže")
            state["complete"] = False
        except FormatError as e:
            log(f"CHYBA FORMÁTU: {e}")
            status = 2
        finally:
            f.save()  # i při výpadku API: hotové dokumenty se příště nestahují znovu
    out_path.write_text(json.dumps(build(state, meps), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    cov = json.loads(out_path.read_text(encoding="utf-8"))["coverage"]
    log(f"PN: výbory do {cov['committee_to']} ({cov['committee_docs']} dokumentů), plénum do {cov['plenary_to']}")
    return status


if __name__ == "__main__":
    sys.exit(main())
