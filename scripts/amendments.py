"""Pozměňovací návrhy (PN) českých poslanců: čisté funkce (parser DOCX, titulky plenárních PN, souhrn po poslancích).

Zdroje (spike: docs/SPIKE_POZMENOVACI_NAVRHY.md):
- PN ve výborech: oficiální DOCX z registru EP, na který odkazuje EP Open Data API (documents, work-type AMENDMENT_LIST).
  Čtou se jen strojové značky šablony EP (<NumAm>, <Members>, <AuNomDe>, <RangeAM> …), nic jiného (CLAUDE.md, výjimka pro PN).
- PN v plénu: EP Open Data API, plenary-documents/{zpráva A10} → inverse_foresees_change_of; autoři jsou v titulku dokumentu.

Počítá se jen v době mandátu a PN s více autory se připisuje každému. Kompromisní PN (vyjednávají stínoví zpravodajové),
PN frakcí a PN výborů v plénu se jednotlivým poslancům nepřipisují. Žádné skóre a žádné pořadí.
"""

from __future__ import annotations

import html
import io
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

from compute_stats import in_mandate

DOCX_URL = "https://data.europarl.europa.eu/distribution/reds_iCmDoc_Amd/{id}/{id}_{lang}.docx"
PDF_URL = "https://data.europarl.europa.eu/distribution/reds_iCmDoc_Amd/{id}/{id}_en.pdf"
PLENARY_URL = "https://www.europarl.europa.eu/doceo/document/{id}_EN.pdf"
COMMITTEE_DOC = re.compile(r"^[A-Z0-9]{4}-AM-\d+$")  # výbory (AGRI-AM-791107) i společné výbory (CJ71-AM-…)
RECENT = 5


class FormatError(ValueError):
    """Dokument nemá očekávanou strukturu (změna šablony EP)."""


def fold(name: str) -> str:
    """Jméno bez diakritiky a velikosti písmen, s jednou mezerou: párování „Jaroslava Pokorná Jermanová“ napříč zdroji."""
    s = unicodedata.normalize("NFKD", name)
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


# --- DOCX výborových PN ---------------------------------------------------------------------------------------------


def docx_text(data: bytes | Path) -> str:
    """Text dokumentu: odstavce na řádky, značky šablony EP (<NumAm> …) zůstanou jako text."""
    with zipfile.ZipFile(data if isinstance(data, Path) else io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return html.unescape(re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n")))


def _tag(name: str) -> re.Pattern:
    return re.compile(rf"<{name}>(.*?)</{name}>", re.S)


_HEAD = {
    k: _tag(t)
    for k, t in {
        "commission": "Commission",
        "date": "Date",
        "range": "RangeAM",
        "type": "TypeAM",
        "proc": "RefProc",
        "proc_type": "RefTypeProc",
    }.items()
}
_NUM = re.compile(r"<NumAm[AB]?>(.*?)</NumAm[AB]?>", re.S)
_MEMBERS, _ON_BEHALF = _tag("Members"), _tag("AuNomDe")


def _strip_code(v: str) -> str:
    return re.sub(r"\{[^}]*\}", "", v).strip()


def parse_committee_docx(text: str, doc_id: str = "") -> dict:
    """Hlavička a PN z textu DOCX. Šablona EP: <RepeatBlock-Amend>/<Amend>/<NumAm>, u dvousloupcových zpráv varianty …A/…B.
    Kompromisní PN (TypeAM COMPROMISE AMENDMENTS) mají jinou šablonu bez autorů: vrací kind="compromise" bez PN.
    Počet PN musí sedět s rozsahem <RangeAM> (např. "483 - 491"), jinak FormatError. Jediný PN (TypeAM AMENDMENT) rozsah nemá."""
    head = {k: (m.group(1).strip() if (m := rx.search(text)) else None) for k, rx in _HEAD.items()}
    date = re.match(r"^\{(\d{1,2})/(\d{1,2})/(\d{4})\}", head["date"] or "")  # strojová část „{20/01/2026}20.1.2026“, i „{2/02/2024}“
    if not date:
        raise FormatError(f"{doc_id}: chybí <Date>, šablona DOCX se změnila")
    out = {
        "date": f"{date.group(3)}-{int(date.group(2)):02d}-{int(date.group(1)):02d}",
        "committees": re.findall(r"\{([A-Z0-9]+)\}", head["commission"] or ""),
        "procedure": f"{head['proc']}{head['proc_type'] or ''}" if head["proc"] else None,
        "range": head["range"],
    }
    if "COMPROMISE" in (head["type"] or "").upper() or "<RepeatBlock-AmCompr>" in text:
        return {**out, "kind": "compromise", "n": None, "authors": {}}
    if not re.search(r"<RepeatBlock-Amend[AB]?>", text):
        raise FormatError(f"{doc_id}: chybí <RepeatBlock-Amend…>, šablona DOCX se změnila")
    amendments = []
    for block in re.split(r"<RepeatBlock-Amend[AB]?>", text)[1:]:
        for am in re.split(r"<Amend[AB]?>", block)[1:]:
            num = _NUM.search(am)
            if not num:
                raise FormatError(f"{doc_id}: PN bez <NumAm>")
            by = am.split("</RepeatBlock-By>")[0]
            members = [n.strip() for m in _MEMBERS.findall(by) for n in re.split(r",|\n", m) if n.strip()]
            amendments.append({"members": members, "on_behalf": bool(_ON_BEHALF.search(by))})
    rng = re.match(r"^(\d+)\s*-\s*(\d+)$", head["range"] or "")
    if rng and int(rng.group(2)) - int(rng.group(1)) + 1 != len(amendments):
        raise FormatError(f"{doc_id}: <RangeAM> {head['range']}, ale načteno {len(amendments)} PN")
    authors: dict[str, list[int]] = {}
    for a in amendments:
        for name in dict.fromkeys(a["members"]):
            row = authors.setdefault(name, [0, 0, 0])  # [podepsal, jako jediný autor, za frakci]
            row[0] += 1
            row[1] += len(a["members"]) == 1
            row[2] += a["on_behalf"]
    return {**out, "kind": "amendments", "n": len(amendments), "authors": authors}


# --- titulky plenárních PN (EP API) ---------------------------------------------------------------------------------

_AM = re.compile(r"^(Pozměňovací(ch)? návrh|Amendment)")
_GROUP = re.compile(r"^(za skupinu|on behalf of the) (?P<g>.+?)( Group)?$")


def classify_plenary(title: str) -> tuple[str, list[str], str | None]:
    """Titulek plenárního PN → (typ, jména, frakce).

    „A10-0031/2 - Pozměňovací návrh 2 - Jméno - za skupinu The Left - Zpráva …“ → group (PN frakce)
    „A10-0259/1 - Pozměňovací návrh 1 - Jméno, Jméno - Zpráva …“                 → members (PN poslanců)
    „A10-0076/1 - Pozměňovací návrh 1 - Jméno - Výbor pro … - Zpráva …“          → committee (předkládá za výbor)
    „Pozměňovací návrh 001-005 - Zpravodaj - Zpráva …“                           → committee (PN výboru ze zprávy)
    Reference bývá i „A10-0170/2025/9“, „A10-0063/34/rev“; EP občas píše „Pozměňovacích návrh“.
    """
    parts = title.split(" - ")
    if len(parts) >= 4 and _AM.match(parts[1]) and not _AM.match(parts[0]):
        people = [p.strip() for p in parts[2].split(",") if p.strip()]
        nxt = parts[3].strip()
        if g := _GROUP.match(nxt):
            return "group", people, g.group("g").strip()
        if re.match(r"^(za |on behalf of the )?(Výbor|Committee)", nxt):
            return "committee", people, None
        return "members", people, None
    if parts and _AM.match(parts[0]):
        return "committee", [], None
    return "unknown", [], None


# --- souhrn po poslancích --------------------------------------------------------------------------------------------


def summarize(state: dict, meps: list[dict]) -> dict:
    """Počty PN po poslancích z data/amendments_state.json (jen v době mandátu, jména přesnou shodou po fold()).

    committee: total (podepsal), sole (jediný autor), on_behalf (za frakci), dossiers (různé procedury), docs a recent
    (posledních RECENT dokumentů s jeho PN, s odkazem na PDF v registru EP). plenary: cosigned (PN poslanců ke zprávám A10).
    Pokrytí = nejnovější datum dokumentu daného druhu; neúplnost (chybí anglická verze) se vykazuje zvlášť."""
    by_name = {fold(f"{m['given_name']} {m['family_name']}"): m for m in meps}
    rows = {m["id"]: {"committee": Counter(), "dossiers": set(), "docs": [], "plenary": 0} for m in meps}
    com = state.get("committee", {})
    for doc_id, d in com.items():
        if d.get("kind") != "amendments":
            continue
        for name, (n, sole, behalf) in d["authors"].items():
            m = by_name.get(fold(name))
            if not m or not in_mandate(m["mandates"], d["date"]):
                continue
            r = rows[m["id"]]
            r["committee"].update(total=n, sole=sole, on_behalf=behalf)
            if d.get("procedure"):
                r["dossiers"].add(d["procedure"])
            r["docs"].append(
                {
                    "doc": doc_id,
                    "date": d["date"],
                    "committees": d["committees"],
                    "procedure": d.get("procedure"),
                    "count": n,
                    "url": PDF_URL.format(id=doc_id),
                }
            )
    plen = state.get("plenary", {})
    for rep in plen.values():
        for a in rep.get("amendments", []):
            if a["kind"] != "members":
                continue
            for name in dict.fromkeys(a["people"]):
                m = by_name.get(fold(name))
                if m and in_mandate(m["mandates"], a["date"]):
                    rows[m["id"]]["plenary"] += a["n"]
    com_days = [d["date"] for d in com.values() if d.get("kind") in ("amendments", "compromise")]
    plen_days = [a["date"] for rep in plen.values() for a in rep.get("amendments", []) if a.get("date")]
    out = {}
    for m in meps:
        r = rows[m["id"]]
        docs = sorted(r["docs"], key=lambda x: (x["date"], x["doc"]), reverse=True)
        out[str(m["id"])] = {
            "committee": {
                "total": r["committee"]["total"],
                "sole": r["committee"]["sole"],
                "on_behalf": r["committee"]["on_behalf"],
                "dossiers": len(r["dossiers"]),
                "docs": len(docs),
                "recent": docs[:RECENT],
            },
            "plenary": {"cosigned": r["plenary"]},
        }
    return {
        "coverage": {
            "committee_to": max(com_days, default=None),
            "plenary_to": max(plen_days, default=None),
            "committee_docs": sum(1 for d in com.values() if d.get("kind") == "amendments"),
            "committee_compromise": sum(1 for d in com.values() if d.get("kind") == "compromise"),
            "committee_pending": sum(1 for d in com.values() if d.get("kind") == "missing"),
        },
        "meps": out,
    }
