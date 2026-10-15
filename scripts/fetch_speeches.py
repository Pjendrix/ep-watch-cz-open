"""Stáhne z EP Open Data API projevy v plénu českých poslanců v 10. období (data/speeches.json).

Endpoint /speeches umí filtrovat podle poslance (person-id), takže se stahuje po poslancích (~2 dotazy na poslance,
EPClient throttluje a opakuje). Každý řádek: ID, datum, typ (ústní projev / písemné prohlášení podle zdroje), délka
z časových značek a bod jednání. Neznámý typ aktivity se neschová do žádné kategorie: skript skončí chybou formátu.
Počítá se až ve sestavení webu (activity.py), jen v době mandátu.

Použití:
    python scripts/fetch_speeches.py [--max-requests 400]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from activity import TYPES, minutes_between
from fetch_meps import EPClient, FormatError, require

TERM_START = "2024-07-16"
PAGE = 100


def short(uri: str | None) -> str | None:
    return None if uri is None else str(uri).rsplit("/", 1)[-1]


def parse_speech(item: dict, mep_id: int) -> dict | None:
    """Jeden záznam z /speeches → řádek, nebo None, když to není projev tohoto poslance (jiný účastník, jiná role)."""
    require(item, ["id", "activity_date", "had_activity_type", "had_participation"], "GET /speeches položka")
    if item["had_activity_type"] not in TYPES:
        raise FormatError(f"/speeches: neznámý typ aktivity {item['had_activity_type']!r}; doplnit do activity.TYPES")
    parts = item["had_participation"]
    parts = parts if isinstance(parts, list) else [parts]
    mine = [p for p in parts if f"person/{mep_id}" in (p.get("had_participant_person") or [])]
    if not mine or not any(str(p.get("participation_role", "")).endswith("/SPEAKER") for p in mine):
        return None
    work = item.get("recorded_in_a_realization_of") or []
    work = work if isinstance(work, list) else [work]
    return {"id": item.get("activity_id") or short(item["id"]), "date": item["activity_date"][:10], "type": TYPES[item["had_activity_type"]],
            "minutes": minutes_between(item.get("activity_start_date"), item.get("activity_end_date")),
            "item": short(work[0].get("is_part_of")) if work and isinstance(work[0], dict) else None}


def fetch_mep(client: EPClient, mep_id: int, since: str = TERM_START) -> list[dict]:
    rows, seen, offset = [], set(), 0
    while True:
        payload = client.get("speeches", {"person-id": mep_id, "offset": offset, "limit": PAGE})
        require(payload, ["data"], f"GET /speeches?person-id={mep_id}")
        batch = payload["data"]
        for item in batch:
            row = parse_speech(item, mep_id)
            if row and row["date"] >= since and row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
        if len(batch) < PAGE:
            return sorted(rows, key=lambda r: (r["date"], r["id"]))
        offset += PAGE


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    args = p.parse_args(argv)
    meps = json.loads((args.data_dir / "meps.json").read_text(encoding="utf-8"))["meps"]
    client = EPClient(min_interval=0.8)
    out = {}
    try:
        for m in meps:
            out[str(m["id"])] = fetch_mep(client, m["id"])
            print(f"{m['name']}: {len(out[str(m['id'])])} záznamů", file=sys.stderr, flush=True)
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    doc = {"source": {"name": "EP Open Data API v2, /speeches", "url": "https://data.europarl.europa.eu/api/v2/speeches", "license": "CC BY 4.0"},
           "term_start": TERM_START, "updated": dt.datetime.now(dt.timezone.utc).date().isoformat(), "meps": out}
    (args.data_dir / "speeches.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"projevy: {sum(len(v) for v in out.values())} záznamů u {len(out)} poslanců", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
