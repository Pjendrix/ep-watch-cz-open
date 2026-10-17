"""Ruční opravy jmen z data/manual/overrides.json (EP u některých jmen neuvádí diakritiku).

Oprava se použije, jen když jméno z EP odpovídá opravě bez diakritiky (např. „Klara DOSTALOVA“
-> „Klára Dostálová“). Když EP jméno změní jinak, skript skončí chybou, aby se oprava zkontrolovala.
Každá oprava má pole note a source; na web se propíše jako name_note.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from compute_stats import FormatError, require


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper()


def apply_name_overrides(meps: list[dict], path: Path) -> int:
    """Upraví meps na místě; vrací počet opravených poslanců."""
    if not path.exists():
        return 0
    doc = json.loads(path.read_text(encoding="utf-8"))
    require(doc, ["names"], path.name)
    by_id = {str(m["id"]): m for m in meps}
    done = 0
    for mid, fix in doc["names"].items():
        require(fix, ["given_name", "family_name", "note", "source"], f"{path.name} {mid}")
        m = by_id.get(mid)
        if m is None:
            continue
        new = f"{fix['given_name']} {fix['family_name']}"
        old = f"{m.get('given_name') or ''} {m.get('family_name') or ''}"
        if strip_accents(old) != strip_accents(new):
            raise FormatError(f"{path.name}: poslanec {mid} má v EP jméno „{old.strip()}“, oprava „{new}“ k němu nesedí; zkontroluj opravu")
        m["given_name"], m["family_name"] = fix["given_name"], fix["family_name"]
        m["name"] = f"{fix['given_name']} {fix['family_name'].upper()}"
        m["name_note"] = f"{fix['note']} Zdroj: {fix['source']}"
        done += 1
    return done
