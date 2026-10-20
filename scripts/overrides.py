"""Ruční opravy jmen z data/manual/overrides.json (EP u některých jmen neuvádí diakritiku).

Oprava se použije, jen když jméno z EP odpovídá opravě bez diakritiky (např. „Klara DOSTALOVA“
-> „Klára Dostálová“). Když EP jméno změní jinak, skript skončí chybou, aby se oprava zkontrolovala.
Každá oprava má pole note a source; na web se propíše jako name_note.

Zobrazované názvy stran (data/manual/party_labels.json, zadání 20. 10. 2026): „TOP09/STAN“ → „TOP 09“, „PIR“ → „Piráti“ …
Přepíšou short_label strany (původní zkratka z EP zůstane jako short_label_ep), aby web i karty měly stejné názvy.
Stejně krátké české názvy frakcí (data/manual/group_labels.json): „PfE“ → „Patrioti“, „Greens/EFA“ → „Zelení“ …
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
        apply_party_labels(meps, path.parent / "party_labels.json")
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
    apply_party_labels(meps, path.parent / "party_labels.json")
    return done


def apply_party_labels(meps: list[dict], path: Path) -> int:
    """Čitelné názvy stran a frakcí do meps[].parties[] a meps[].groups[] (short_label, na místě); vrací počet přepsaných členství.
    Frakce z group_labels.json vedle party_labels.json."""
    labels = load_party_labels(path)
    glabels = load_group_labels(path.parent / "group_labels.json")
    done = 0
    for m in meps:
        for items, key, table in ((m.get("parties", []), "org_id", labels), (m.get("groups", []), "code", glabels)):
            for p in items:
                new = table.get(str(p.get(key)))
                if new and p.get("short_label") != new:
                    p.setdefault("short_label_ep", p.get("short_label"))
                    p["short_label"] = new
                    done += 1
    return done


def load_group_labels(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    require(doc, ["groups"], path.name)
    bad = [k for k, v in doc["groups"].items() if not (isinstance(v, str) and v.strip())]
    if bad:
        raise FormatError(f"{path.name}: prázdný název u {bad}")
    return doc["groups"]


def load_party_labels(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    require(doc, ["parties"], path.name)
    bad = [k for k, v in doc["parties"].items() if not (k.isdigit() and isinstance(v, str) and v.strip())]
    if bad:
        raise FormatError(f"{path.name}: neplatný záznam {bad} (klíč = ID strany, hodnota = název)")
    return doc["parties"]
