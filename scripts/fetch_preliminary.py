"""Stáhne předběžné výsledky jmenovitých hlasování ze dnů zasedání, které HowTheyVote ještě nemá (data/preliminary/).

Zdroj: EP Open Data API, GET /meetings/MTG-PL-{datum}/decisions (jeden dotaz na den). Pravidla v scripts/preliminary.py.
Dny zasedání bere z programu (data/agenda.json → sittings), poslední den v datech HowTheyVote z data/votes.
Soubory dnů, které už HowTheyVote má, smaže. Soubor se přepíše, jen když se změnila hlasování (ne kvůli času stažení).

Použití:
    python scripts/fetch_preliminary.py            # stáhnout dnešní a dřívější nezpracované dny zasedání
    python scripts/fetch_preliminary.py --due      # jen vypsat due=true/false (pro GitHub Actions)
    python scripts/fetch_preliminary.py --prune    # jen smazat dny, které už HowTheyVote má (týdenní aktualizace)
    python scripts/fetch_preliminary.py --day 2026-10-22 --force   # konkrétní den i když ho HowTheyVote už má (test)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fetch_meps import EPClient
from fetch_meps import FormatError as ApiFormatError
from preliminary import FormatError, check_day, day_file, htv_last_day, parse_decisions, require, stale_files

PRAGUE = ZoneInfo("Europe/Prague")


def sittings(data_dir: Path) -> list[str]:
    path = data_dir / "agenda.json"
    if not path.exists():
        raise FormatError(f"chybí {path} (stahuje fetch_agenda.py)")
    agenda = json.loads(path.read_text(encoding="utf-8"))
    require(agenda, ["sittings"], "agenda.json")
    return sorted(agenda["sittings"])


def due_days(all_sittings: list[str], covered: str | None, today: str) -> list[str]:
    """Dny zasedání do dneška včetně, které HowTheyVote ještě nemá."""
    return [d for d in all_sittings if d <= today and (covered is None or d > covered)]


def is_due(all_sittings: list[str], covered: str | None, today: str) -> bool:
    """Běžet dnes? Ve dni zasedání a den po posledním dni zasedání (dohnat večerní hlasování), dokud je co stahovat."""
    yesterday = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()
    return bool(due_days(all_sittings, covered, today)) and (today in all_sittings or yesterday in all_sittings)


def same_votes(path: Path, new: dict) -> bool:
    if not path.exists():
        return False
    old = json.loads(path.read_text(encoding="utf-8"))
    return old.get("votes") == new["votes"]


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    p.add_argument("--day", help="jen tento den (RRRR-MM-DD)")
    p.add_argument("--force", action="store_true", help="stáhnout --day, i když ho HowTheyVote už má")
    p.add_argument("--due", action="store_true", help="jen vypsat due=true/false")
    p.add_argument("--prune", action="store_true", help="jen smazat dny, které už HowTheyVote má")
    p.add_argument("--today", help=argparse.SUPPRESS)  # pro testy
    args = p.parse_args(argv)
    data_dir: Path = args.data_dir
    out_dir = data_dir / "preliminary"
    now = datetime.now(PRAGUE)
    today = args.today or now.date().isoformat()
    try:
        covered = htv_last_day(data_dir / "votes")
        days_all = sittings(data_dir)
        if args.due:
            print(f"due={'true' if is_due(days_all, covered, today) else 'false'}")
            return 0
        for path in stale_files(out_dir, covered):
            path.unlink()
            print(f"smazáno {path.name}: HowTheyVote už má hlasování do {covered}", file=sys.stderr)
        if args.prune:
            return 0
        days = [args.day] if args.day else due_days(days_all, covered, today)
        if args.day and covered and args.day <= covered and not args.force:
            print(f"{args.day}: HowTheyVote už má hlasování do {covered}, nic nestahuji (--force pro test)", file=sys.stderr)
            return 0
        meps = json.loads((data_dir / "meps.json").read_text(encoding="utf-8"))
        require(meps, ["meps"], "meps.json")
        groups = json.loads((data_dir / "groups.json").read_text(encoding="utf-8"))
        ep_to_code = {g["ep_code"]: g["code"] for g in groups if g.get("ep_code")}
        client = EPClient()
        for day in days:
            payload = client.get(f"meetings/MTG-PL-{day}/decisions")
            votes = parse_decisions(payload, day)
            if not votes:
                print(f"{day}: zatím žádné jmenovité hlasování", file=sys.stderr)
                continue
            data = day_file(day, votes, meps["meps"], ep_to_code, now.isoformat(timespec="minutes"))
            check_day(data)
            path = out_dir / f"{day}.json"
            if same_votes(path, data):
                print(f"{day}: beze změny ({len(votes)} hlasování)", file=sys.stderr)
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
            print(
                f"{day}: uloženo {len(votes)} jmenovitých hlasování, z toho {sum(v['main'] for v in data['votes'])} hlavních",
                file=sys.stderr,
            )
    except (FormatError, ApiFormatError) as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
