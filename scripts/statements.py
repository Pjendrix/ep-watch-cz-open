"""Vyjádření poslanců (V7, právo na odpověď): data/manual/statements.json, ručně schválené správcem.

Každé vyjádření: mep_id, scope („metric:attendance“, „metric:group_loyalty“, „metric:cz_agreement“,
„metric:presence“, „metric:attendance_main“ nebo číslo hlasování), text (nejvýš 300 znaků), date (RRRR-MM-DD),
source (odkaz nebo popis, odkud vyjádření je). Na webu vždy se štítkem „vyjádření poslance, neověřeno“.
Kontroluje check_data.py (validate); chybný záznam = chyba, web se nesestaví s nevalidním obsahem.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

MAX_LEN = 300
METRICS = {"attendance", "attendance_main", "group_loyalty", "cz_agreement", "presence"}
LABEL = "vyjádření poslance, neověřeno"


def validate(items: list, mep_ids: set[int]) -> list[str]:
    """Seznam chyb (prázdný = v pořádku)."""
    errs = []
    for i, s in enumerate(items):
        where = f"manual/statements.json[{i}]"
        missing = [k for k in ("mep_id", "scope", "text", "date", "source") if k not in s]
        if missing:
            errs.append(f"{where}: chybí {', '.join(missing)}")
            continue
        if s["mep_id"] not in mep_ids:
            errs.append(f"{where}: poslanec {s['mep_id']} není v meps.json")
        sc = s["scope"]
        if not (isinstance(sc, int) or (isinstance(sc, str) and sc.startswith("metric:") and sc[7:] in METRICS)):
            errs.append(f"{where}: neznámý scope {sc!r} (metric:… nebo číslo hlasování)")
        if not isinstance(s["text"], str) or not s["text"].strip() or len(s["text"]) > MAX_LEN:
            errs.append(f"{where}: text musí mít 1–{MAX_LEN} znaků")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s["date"])):
            errs.append(f"{where}: datum není RRRR-MM-DD")
        if not str(s["source"]).strip():
            errs.append(f"{where}: chybí zdroj")
    return errs


def load(data_dir: Path) -> list[dict]:
    path = data_dir / "manual" / "statements.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("statements", [])


def for_scope(items: list[dict], mep_id: int | None, scope) -> list[dict]:
    return [s for s in items if (mep_id is None or s["mep_id"] == mep_id) and s["scope"] == scope]


def html(items: list[dict], names: dict[int, str] | None = None) -> str:
    """Vyjádření se štítkem; zdroj jako odkaz, když je to adresa."""
    if not items:
        return ""
    from web_ui import esc, fmt_date  # jen pro web; validate/load jsou i ve veřejném repu (check_data.py)

    def src(x):
        s = str(x["source"])
        return f'<a href="{esc(s)}" rel="nofollow noopener">zdroj</a>' if s.startswith("https://") else esc(s)

    return "".join(
        f'<blockquote class="stmt"><p class="stmt-tag">{LABEL}</p>'
        f'<p>{esc(x["text"])}</p><p class="small muted">'
        + (f"{esc(names.get(x['mep_id'], ''))} · " if names else "")
        + f"{fmt_date(x['date'])} · {src(x)}</p></blockquote>"
        for x in items
    )
