"""Zlaté kontroly (V18): ručně ověřená fakta z oficiálních zdrojů EP v data/manual/golden.json.

Každý fakt ověřil správce proti oficiálnímu zdroji (zápis z jednání, stránka hlasování EP, profil poslance)
a zapsal ho se zdrojem. check_data.py porovná fakta s daty: nesoulad je chyba a týdenní data se necommitnou.
Hodnoty sem nikdy nedoplňuje skript ani AI (CLAUDE.md: žádná vymyšlená data).

Druhy faktů:
  vote       {"kind": "vote", "vote_id": 123, "result": "ADOPTED", "for": 400, "against": 200, "abstention": 30, ...}
             result a počty jsou nepovinné, ale aspoň jedno musí být.
  committee  {"kind": "committee", "mep_id": 1, "code": "ENVI", "role": "MEMBER", "date": "2025-03-01", ...}
             poslanec byl k datu ve výboru (role nepovinná).
Každý fakt má navíc source (adresa oficiálního zdroje), verified_by a verified_on (RRRR-MM-DD).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

COMMON = ("source", "verified_by", "verified_on")
COUNTS = ("for", "against", "abstention")


def load(data_dir: Path) -> list[dict]:
    path = data_dir / "manual" / "golden.json"
    return json.loads(path.read_text(encoding="utf-8")).get("facts", []) if path.exists() else []


def check(facts: list[dict], votes_by_id: dict[int, dict], meps_by_id: dict[int, dict]) -> list[str]:
    """Seznam chyb (prázdný = vše sedí)."""
    errs = []
    for i, f in enumerate(facts):
        where = f"manual/golden.json[{i}]"
        missing = [k for k in COMMON if not f.get(k)]
        if missing:
            errs.append(f"{where}: chybí {', '.join(missing)}")
            continue
        if not str(f["source"]).startswith("https://") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(f["verified_on"])):
            errs.append(f"{where}: source musí být https:// adresa a verified_on RRRR-MM-DD")
            continue
        if f.get("kind") == "vote":
            v = votes_by_id.get(f.get("vote_id"))
            if v is None:
                errs.append(f"{where}: hlasování {f.get('vote_id')} v datech není")
                continue
            if "result" not in f and not any(k in f for k in COUNTS):
                errs.append(f"{where}: chybí result nebo počty")
            if "result" in f and f["result"] != v.get("result"):
                errs.append(f"{where}: hlasování {v['id']} výsledek {v.get('result')}, ověřeno {f['result']}")
            for k in COUNTS:
                if k in f and f[k] != v["counts"][k]:
                    errs.append(f"{where}: hlasování {v['id']} {k}={v['counts'][k]}, ověřeno {f[k]}")
        elif f.get("kind") == "committee":
            m = meps_by_id.get(f.get("mep_id"))
            if m is None:
                errs.append(f"{where}: poslanec {f.get('mep_id')} v datech není")
                continue
            day = f.get("date") or ""
            hit = [
                c
                for c in m.get("committees") or []
                if c["code"] == f.get("code") and c["start"] <= day and (not c.get("end") or c["end"] >= day)
            ]
            if not hit:
                errs.append(f"{where}: poslanec {m['id']} k {day} ve výboru {f.get('code')} podle dat není")
            elif f.get("role") and f["role"] not in {c["role"] for c in hit}:
                errs.append(
                    f"{where}: poslanec {m['id']} ve výboru {f.get('code')} má roli {[c['role'] for c in hit]}, ověřeno {f['role']}"
                )
        else:
            errs.append(f"{where}: neznámý druh {f.get('kind')!r} (vote nebo committee)")
    return errs
