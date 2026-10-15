"""Stáhne z EP Open Data API prezenční listiny plenárních dnů 10. období (data/attendance.json).

Endpoint /meetings vrací po letech všechny plenární dny včetně prezenční listiny (had_participant_person) a omluvených
(had_excused_person), takže stačí pár dotazů. Ukládají se jen dny, ke kterým listina existuje (budoucí a ještě nezpracované
dny se nepočítají jako neúčast), a z listiny jen čeští poslanci. Chybějící očekávané pole = chyba formátu.

Použití:
    python scripts/fetch_attendance.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from fetch_meps import EPClient, FormatError, require

TERM_START = "2024-07-16"
SITTING = "def/ep-activities/PLENARY_SITTING"


def person_ids(value) -> list[int]:
    value = value if isinstance(value, list) else ([] if value is None else [value])
    return [int(str(p).rsplit("/", 1)[-1]) for p in value]


def parse_day(item: dict, cz_ids: set[int], term_start: str = TERM_START, today: str | None = None) -> dict | None:
    """Plenární den → {date, attendees, present, excused} (jen ČR), nebo None (jiný typ, jiné období, bez listiny)."""
    require(item, ["id", "activity_date", "had_activity_type"], "GET /meetings položka")
    if item["had_activity_type"] != SITTING or item["activity_date"][:10] < term_start:
        return None
    if today and item["activity_date"][:10] > today:
        return None
    attendees = person_ids(item.get("had_participant_person"))
    if not attendees:
        return None  # listina ještě není (nebo den bez jednání): nepočítat jako neúčast
    return {"date": item["activity_date"][:10], "attendees": len(set(attendees)),
            "present": sorted(set(attendees) & cz_ids), "excused": sorted(set(person_ids(item.get("had_excused_person"))) & cz_ids)}


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    args = p.parse_args(argv)
    today = dt.datetime.now(dt.timezone.utc).date()
    cz_ids = {m["id"] for m in json.loads((args.data_dir / "meps.json").read_text(encoding="utf-8"))["meps"]}
    client = EPClient(min_interval=0.8)
    days = {}
    try:
        for year in range(int(TERM_START[:4]), today.year + 1):
            payload = client.get("meetings", {"year": year, "limit": 500})
            require(payload, ["data"], f"GET /meetings?year={year}")
            for item in payload["data"]:
                day = parse_day(item, cz_ids, today=today.isoformat())
                if day:
                    days[day["date"]] = day
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    doc = {"source": {"name": "EP Open Data API v2, /meetings (prezenční listiny)", "url": "https://data.europarl.europa.eu/api/v2/meetings",
                      "license": "CC BY 4.0"},
           "term_start": TERM_START, "updated": today.isoformat(), "days": [days[k] for k in sorted(days)]}
    (args.data_dir / "attendance.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"prezenční listiny: {len(days)} plenárních dnů", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
