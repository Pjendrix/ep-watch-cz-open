"""Přijaté texty z EP Open Data API (B1): ke každému přijatému závěrečnému hlasování oficiální přijatý text (TA).

Proč: pole texts_adopted_reference z HowTheyVote je od června 2026 prázdné a u zákonů ve 2. fázi ukazuje na text
z 1. čtení. EP Open Data API má ke každé proceduře přijaté texty (TA-10-RRRR-NNNN) s datem a dokumentem, který přijímají.

Párování hlasování → TA (jen oficiální API, žádný scraping HTML):
  1. /procedures/{RRRR-NNNN} → created_a_realization_of: dokumenty procedury, z nich TA-…,
  2. /adopted-texts/{TA} → document_date a adopts (např. eli/dl/doc/B-10-2026-0424),
  3. TA patří k hlasování, když se datum rovná dni hlasování a adopts obsahuje dokument hlasování
     (A10-0241/2026 → A-10-2026-0241, RC-B10-0452/2026 → RC-10-2026-0452); když dokument nesedí, jediný TA toho dne.
Výstup data/adopted_texts.json: {"votes": {id: {"ta", "date"}}, "unmatched": {id: den kontroly}}. Nenalezené se
znovu zkouší jen u hlasování z posledních 90 dnů (text může vyjít později). Throttling a opakování z EPClient.

load_votes() (compute_stats.py) podle souboru doplní texts_adopted_reference (P10_TA(RRRR)NNNN), takže opravený odkaz
používá celý web. Text sám se neukládá: vote_summaries.py si stáhne český DOCX do .cache/ a pošle modelu úryvek (excerpt).

Použití:
    python scripts/adopted_texts.py           # doplní data/adopted_texts.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
DIST = "https://data.europarl.europa.eu/distribution/doc"
RECHECK_DAYS = 90
EXCERPT_CHARS = 30000  # ≈ 8 000 tokenů (čeština ≈ 3,7 znaku na token)
TA_RE = re.compile(r"TA-(\d+)-(20\d\d)-(\d{4})")  # EP API má i chybná čísla (TA-10-0026-0030): jen platný rok
REF_RE = re.compile(r"^(RC-B|A|B|C)(\d+)-(\d{4})/(\d{4})")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class FormatError(ValueError):
    pass


def doc_id(reference: str | None) -> str | None:
    """Číslo dokumentu hlasování ve tvaru EP API: A10-0241/2026 → A-10-2026-0241, RC-B10-0452/2026 → RC-10-2026-0452."""
    m = REF_RE.match(reference or "")
    if not m:
        return None
    kind = "RC" if m[1] == "RC-B" else m[1]
    return f"{kind}-{m[2]}-{m[4]}-{m[3]}"


def proc_id(reference: str | None) -> str | None:
    """2026/2868(RSP) → 2026-2868 (identifikátor procedury v EP API)."""
    m = re.match(r"^(\d{4})/(\d{4})\([A-Z]{3}\)$", reference or "")
    return f"{m[1]}-{m[2]}" if m else None


def ta_reference(ta: str) -> str:
    """TA-10-2026-0342 → P10_TA(2026)0342 (tvar pole texts_adopted_reference z HowTheyVote)."""
    m = TA_RE.fullmatch(ta)
    if not m:
        raise FormatError(f"neočekávané číslo přijatého textu: {ta}")
    return f"P{m[1]}_TA({m[2]}){m[3]}"


def ta_url(ta: str, ext: str = "pdf") -> str:
    return f"{DIST}/{ta}_cs.{ext}"


def _first(doc: dict) -> dict:
    items = doc.get("data") if isinstance(doc, dict) else None
    if isinstance(items, list) and items:
        return items[0]
    if isinstance(doc, dict) and doc.get("id"):
        return doc
    raise FormatError("odpověď EP API nemá položku data[0]")


def procedure_tas(client, pid: str) -> list[str]:
    p = _first(client.get(f"procedures/{pid}"))
    if "created_a_realization_of" not in p:
        raise FormatError(f"procedura {pid}: chybí pole created_a_realization_of")
    return sorted({m[0] for x in p.get("created_a_realization_of") or [] if (m := TA_RE.search(str(x)))})


def ta_meta(client, ta: str) -> dict:
    t = _first(client.get(f"adopted-texts/{ta}"))
    if "document_date" not in t:
        raise FormatError(f"{ta}: chybí pole document_date")
    # adopts u některých textů chybí: pak se páruje jen podle data (jediný text toho dne)
    return {"date": str(t["document_date"])[:10], "adopts": [str(x).rsplit("/", 1)[-1] for x in t.get("adopts") or []]}


def match(vote: dict, tas: dict[str, dict]) -> str | None:
    """TA k hlasování: stejný den a přijímá dokument hlasování; jinak jediný TA toho dne."""
    same_day = [ta for ta, m in tas.items() if m["date"] == vote["date"]]
    doc = doc_id(vote.get("reference"))
    exact = [ta for ta in same_day if doc and doc in tas[ta]["adopts"]]
    if len(exact) == 1:
        return exact[0]
    return same_day[0] if len(same_day) == 1 else None


def update(votes: list[dict], old: dict, client, today: str, log=print, checkpoint=None) -> dict:
    """Doplní párování pro přijatá závěrečná hlasování, která ho ještě nemají."""
    from vote_kinds import is_final

    found = dict(old.get("votes") or {})
    unmatched = dict(old.get("unmatched") or {})
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=RECHECK_DAYS)).isoformat()
    todo = [
        v
        for v in votes
        if is_final(v)
        and v.get("result") == "ADOPTED"
        and proc_id((v.get("procedure") or {}).get("reference"))
        and str(v["id"]) not in found
        and (str(v["id"]) not in unmatched or v["date"] >= cutoff)
    ]
    proc_cache: dict[str, list[str]] = {}
    ta_cache: dict[str, dict | None] = {}
    for i, v in enumerate(sorted(todo, key=lambda x: (x["date"], x["id"]), reverse=True)):
        pid = proc_id(v["procedure"]["reference"])
        if pid not in proc_cache:
            try:
                proc_cache[pid] = procedure_tas(client, pid)
            except Exception as e:  # noqa: BLE001 – jedna procedura nesmí zastavit ostatní; zkusí se příště
                log(f"procedura {pid}: {e}")
                proc_cache[pid] = []
        for ta in proc_cache[pid]:
            if ta not in ta_cache:
                try:
                    ta_cache[ta] = ta_meta(client, ta)
                except Exception as e:  # noqa: BLE001 – chybný nebo nedostupný dokument EP přeskočit
                    log(f"{ta}: {e}")
                    ta_cache[ta] = None
        ta = match(v, {t: ta_cache[t] for t in proc_cache[pid] if ta_cache[t]})
        if ta:
            found[str(v["id"])] = {"ta": ta, "date": ta_cache[ta]["date"]}
            unmatched.pop(str(v["id"]), None)
        else:
            unmatched[str(v["id"])] = today
        if checkpoint and i % 50 == 49:
            checkpoint(found, unmatched)
    log(f"přijaté texty: {len(todo)} hlasování ke kontrole, spárováno celkem {len(found)}, bez textu {len(unmatched)}")
    return result(found, unmatched, today)


def result(found: dict, unmatched: dict, today: str) -> dict:
    return {
        "note": "Přijaté texty (TA) k přijatým závěrečným hlasováním z EP Open Data API (scripts/adopted_texts.py).",
        "source": {"name": "EP Open Data API v2", "url": "https://data.europarl.europa.eu/api/v2", "license": "CC BY 4.0"},
        "updated": today,
        "votes": dict(sorted(found.items(), key=lambda kv: int(kv[0]))),
        "unmatched": dict(sorted(unmatched.items(), key=lambda kv: int(kv[0]))),
    }


def apply(votes: list[dict], data_dir: Path) -> None:
    """Doplní k hlasováním texts_adopted_reference podle EP API (má přednost před HowTheyVote)."""
    path = data_dir / "adopted_texts.json"
    if not path.exists():
        return
    found = json.loads(path.read_text(encoding="utf-8")).get("votes") or {}
    for v in votes:
        hit = found.get(str(v["id"]))
        if hit:
            v["texts_adopted_reference"] = ta_reference(hit["ta"])


# --- text pro AI shrnutí (vote_summaries.py) -------------------------------------------------------------


def docx_text(data: bytes) -> list[str]:
    """Odstavce z DOCX (word/document.xml), bez knihoven třetích stran."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise FormatError(f"přijatý text není čitelný DOCX: {e}") from e
    out = []
    for p in root.iter(f"{W}p"):
        t = "".join(x.text or "" for x in p.iter(f"{W}t")).strip()
        if t:
            out.append(re.sub(r"\s+", " ", t))
    return out


def excerpt(paragraphs: list[str], limit: int = EXCERPT_CHARS) -> str:
    """Deterministický úryvek: bez citací „s ohledem na …“ (odkazy na dokumenty, ne obsah), od začátku do limitu
    po celých odstavcích. Body odůvodnění („vzhledem k …“) a první články zůstávají."""
    out, size = [], 0
    for p in paragraphs:
        if re.match(r"^[–-]?\s*s ohledem na\b", p, re.I):
            continue
        if size + len(p) > limit:
            break
        out.append(p)
        size += len(p) + 1
    return "\n".join(out)


def fetch_text(ta: str, cache_dir: Path, session=None) -> str | None:
    """Úryvek přijatého textu (český DOCX z EP Open Data), s cache na disku; bez souboru None."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{ta}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    import requests

    r = (session or requests).get(ta_url(ta, "docx"), timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    text = excerpt(docx_text(r.content))
    if not text:
        raise FormatError(f"{ta}: přijatý text je prázdný")
    path.write_text(text, encoding="utf-8")
    return text


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = p.parse_args(argv)
    from compute_stats import FormatError as StatsFormatError
    from compute_stats import load_votes
    from fetch_meps import EPClient
    from fetch_meps import FormatError as ApiFormatError

    out_path = args.data_dir / "adopted_texts.json"
    old = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    try:
        _, votes = load_votes(args.data_dir / "votes")
        today = dt.date.today().isoformat()

        def save(found, unmatched):  # průběžně: první běh má stovky dotazů, výpadek nesmí zahodit hotové
            out_path.write_text(json.dumps(result(found, unmatched, today), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

        out = update(votes, old, EPClient(), today, log=lambda m: print(m, file=sys.stderr), checkpoint=save)
    except (FormatError, StatsFormatError, ApiFormatError) as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
