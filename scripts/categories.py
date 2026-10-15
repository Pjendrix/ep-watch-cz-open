"""Kategorie hlasování pro karty (srozumitelné skupiny místo stovek témat OEIL).

Pevná tabulka pravidel nad kódy témat OEIL (úroveň 1–2 až 3), žádná AI. Hlasování může mít víc kategorií:
na kartě je hlavní (první podle priority) a „+n“, v detailu všechny. Hlasování bez témat OEIL kategorii nemá a nic se nedomýšlí.
Priorita: konkrétní témata před obecnými (obrana > klima a energie > doprava > …> instituce).
"""

from __future__ import annotations

# (klíč, název, ikona = tvary SVG 24×24 pro stroke currentColor)
CATEGORIES = [
    ("def", "Obrana a bezpečnost", '<path d="M12 3l7.5 3v5.5c0 4.4-3 8-7.5 9.5-4.5-1.5-7.5-5.1-7.5-9.5V6L12 3z"/>'),
    ("env", "Klima, příroda a energie", '<path d="M5 19c-.5-8.5 4.5-14 14-14 .5 9.5-5 14.5-13 14zM5 19l7-7"/>'),
    ("tra", "Doprava", '<path d="M2.5 6.5h11v10h-11zM13.5 9.5h4.2l3.3 3.3v3.7h-7.5"/><circle cx="7" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/>'),
    ("agr", "Zemědělství a potraviny", '<path d="M12 21v-9"/><path d="M12 12c0-4-3-6.5-7.5-6.5C4.5 9.5 7.5 12 12 12z"/><path d="M12 14c0-3.2 2.5-5.5 6.5-5.5 0 3.5-2.8 5.5-6.5 5.5z"/>'),
    ("dig", "Digitální svět a věda", '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 3.5V7M14 3.5V7M10 17v3.5M14 17v3.5M3.5 10H7M3.5 14H7M17 10h3.5M17 14h3.5"/>'),
    ("soc", "Zdraví a sociální věci", '<path d="M12 20s-7.5-4.6-7.5-10.2A4.2 4.2 0 0 1 12 7.3a4.2 4.2 0 0 1 7.5 2.5C19.5 15.4 12 20 12 20z"/>'),
    ("eco", "Průmysl a vnitřní trh", '<path d="M3 20V10.5L9 14v-3.5l6 3.5V6h3.5v14H3z"/>'),
    ("abr", "Vnější vztahy a obchod", '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3.2 3 3.2 15 0 18M12 3c-3.2 3-3.2 15 0 18"/>'),
    ("jus", "Spravedlnost a migrace", '<path d="M12 4v16M7 20h10M5 7.5h14"/><path d="M5 7.5L2.5 14a2.7 2.7 0 0 0 5 0L5 7.5zM19 7.5L16.5 14a2.7 2.7 0 0 0 5 0L19 7.5z"/>'),
    ("civ", "Práva a občanství", '<circle cx="9" cy="8.5" r="3.2"/><path d="M3 20c0-3.4 2.7-6 6-6s6 2.6 6 6"/><circle cx="17" cy="9.5" r="2.5"/><path d="M17.5 14.2c2.2.4 3.7 2.2 3.7 4.8"/>'),
    ("fin", "Rozpočet a finance", '<rect x="3" y="6.5" width="18" height="11" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6.5 12h.01M17.5 12h.01"/>'),
    ("ins", "Instituce a pravidla EU", '<path d="M3 9.5L12 4l9 5.5H3zM5.5 9.5v8M9.8 9.5v8M14.2 9.5v8M18.5 9.5v8M3.5 20.5h17"/>'),
]
ORDER = [c[0] for c in CATEGORIES]
LABEL = {c[0]: c[1] for c in CATEGORIES}
ICON = {c[0]: c[2] for c in CATEGORIES}


def category_of_code(code: str) -> str | None:
    """Kategorie pro jeden kód OEIL (např. „3.40.09“); None, když pravidlo nepasuje."""
    p = code.split(".")
    if code.startswith(("3.40.09", "6.10")):
        return "def"
    if p[0] == "6" or code.startswith(("5.03", "8.20")):
        return "abr"
    if code.startswith(("3.60", "3.70")):
        return "env"
    if code.startswith("3.20"):
        return "tra"
    if code.startswith(("3.10", "3.15", "4.60.04")):
        return "agr"
    if code.startswith(("2.50", "2.70")):
        return "fin"
    if code.startswith(("3.40", "3.45")) or p[0] == "2":
        return "eco"
    if code.startswith(("3.30", "3.50", "1.20.09")):
        return "dig"
    if code.startswith(("8.70", "4.70")) or p[0] == "5":
        return "fin"
    if code.startswith(("4.10", "4.15", "4.20", "4.40", "4.50", "4.60")):
        return "soc"
    if p[0] == "1":
        return "civ"
    if p[0] == "7":
        return "jus"
    if p[0] == "8":
        return "ins"
    return None


def categories_for(vote: dict) -> list[str]:
    """Klíče kategorií hlasování seřazené podle priority (první = hlavní). Prázdný seznam = bez kategorie."""
    codes = [t["code"] for t in ((vote.get("topics") or {}).get("oeil") or [])]
    found = {c for c in map(category_of_code, codes) if c}
    return [k for k in ORDER if k in found]


def icon_svg(key: str) -> str:
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{ICON[key]}</svg>')


def icon_inner(key: str) -> str:
    """Tvary SVG bez obalu (pro JS: web si obalí vlastním <svg>)."""
    return ICON[key]
