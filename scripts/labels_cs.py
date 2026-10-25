"""Český popis hlasování z francouzského pole description (HowTheyVote), podle pravidel.

Žádná AI: postupné nahrazení známých výrazů. Když po překladu zůstane francouzské slovo,
vrací None a web ukáže originál (nikdy polopřeklad).
"""

from __future__ import annotations

import re

# Celé fráze (pořadí je důležité: delší dřív).
PHRASES = [
    (r"\(correspond à l'article (\d+) dans l'amendement (\d+)\)", r"(odpovídá článku \1 v PN \2)"),
    (r"Demande de renvoi \(article (\d+), paragraphe (\d+), du règlement\)", r"žádost o vrácení (čl. \1 odst. \2 jednacího řádu)"),
    (r"Demande de renvoi \(article (\d+), paragraphe (\d+), du ;? ?règlement\)", r"žádost o vrácení (čl. \1 odst. \2 jednacího řádu)"),
    (r"Demande d'ajournement du groupe (.+)$", r"žádost frakce \1 o odložení hlasování"),
    (r"Proposition de décision concernant la décharge", "návrh rozhodnutí o udělení absolutoria"),
    (r"Proposition de rejet de la position du Conseil", "návrh na zamítnutí postoje Rady"),
    (r"Proposition de résolution de la commission (\w+)", r"návrh usnesení výboru \1"),
    (r"Abrogation de la ", "zrušení "),
    (r"Proposition de résolution de remplacement", "alternativní návrh usnesení"),
    (r"Proposition de résolution commune", "společný návrh usnesení"),
    (r"Proposition de r[ée]solution", "návrh usnesení"),
    (r"Proposition de la Commission et amendements", "návrh Komise a pozměňovací návrhy"),
    (r"Proposition de la Commission et amendement", "návrh Komise a pozměňovací návrh"),
    (r"Proposition de la Commission au Conseil", "návrh Komise Radě"),
    (r"Proposition de la Commission", "návrh Komise"),
    (r"Projet de décision du Conseil", "návrh rozhodnutí Rady"),
    (r"Proposition de décision du Conseil", "návrh rozhodnutí Rady"),
    (r"Projet de règlement du Conseil", "návrh nařízení Rady"),
    (r"Proposition de règlement du Conseil", "návrh nařízení Rady"),
    (r"Proposition de décision", "návrh rozhodnutí"),
    (r"Projet de recommandation", "návrh doporučení"),
    (r"Projet du Conseil", "návrh Rady"),
    (r"Projet commun", "společný text dohodovacího výboru"),
    (r"Accord provisoire", "prozatímní dohoda"),
    (r"non modifiée", "beze změn"),
    (r"Décision d'engager des négociations interinstitutionnelles", "rozhodnutí zahájit jednání s Radou"),
    (r"Demande de décision d'urgence", "žádost o naléhavý postup"),
    (r"Demande de procéder au vote sur les amendements", "žádost o hlasování o pozměňovacích návrzích"),
    (r"Demande d'ajournement du vote", "žádost o odložení hlasování"),
    (r"Demande de renvoi en commission", "žádost o vrácení do výboru"),
    (r"Proposition de rejet", "návrh na zamítnutí"),
    (r"Rejet", "zamítnutí"),
    (r"Amendements de la commission (compétente|responsable)", "pozměňovací návrhy příslušného výboru"),
    (r"Amendements de la commission", "pozměňovací návrhy výboru"),
    (r"vote en bloc", "hromadné hlasování"),
    (r"texte original", "původní znění"),
    (r"note de bas de page", "poznámka pod čarou"),
    (r"entrée", "položka"),
    (r"votes séparés et votes par division", "oddělená a dělená hlasování"),
    (r"votes séparés", "oddělená hlasování"),
    (r"vote séparé", "oddělené hlasování"),
    (r"ensemble du texte", "celý text"),
    (r"Procédure d'approbation", "postup souhlasu"),
]
# Odkazy na místo v textu.
PLACES = [
    (r"[Aa]près le considérant ([A-Z]{1,3}|\d+)", r"za bodem odůvodnění \1"),
    (r"Avant le considérant ([A-Z]{1,3}|\d+)", r"před bodem odůvodnění \1"),
    (r"Considérant ([A-Z]{1,3}|\d+)", r"bod odůvodnění \1"),
    (r"Après le visa (\d+)", r"za právním východiskem \1"),
    (r"Visa (\d+)", r"právní východisko \1"),
    (r"Règlement \((UE|CE)\) (nº |č\. )?(\d+/\d+)", lambda m: f"nařízení ({'EU' if m[1] == 'UE' else 'ES'}) {'č. ' if m[2] else ''}{m[3]}"),
    (r"Directive \(UE\) (nº |č\. )?(\d+/\d+)", r"směrnice (EU) \1\2"),
    (r"Directive (\d+/\d+) \(UE\)", r"směrnice (EU) \1"),
    (r"Directive (\d+/\d+)/CE", r"směrnice \1/ES"),
    (r"Décision (\d+/\d+)/CEE du Conseil", r"rozhodnutí Rady \1/EHS"),
    (r"[Ll]igne directrice n° (\d+)", r"hlavní směr č. \1"),
    (r"[Rr]ecommandation n° (\d+)", r"doporučení č. \1"),
    (r"[Rr]ecommandation (\d+)", r"doporučení \1"),
    (r"[Pp]artie ([A-Z]+|[IVX]+)\b", r"část \1"),
    (r"Article premier", "článek 1"),
    (r"[Aa]près le (premier|deuxième) alinéa", lambda m: f"za {ORDINAL_M[m[1]]}m pododstavcem"),
    (r"(premier|deuxième|troisième|quatrième|cinquième) alinéa", lambda m: f"{ORDINAL_M[m[1]]} pododstavec"),
    (r"deuxième phrase", "druhá věta"),
    (r"deuxième tiret", "druhá odrážka"),
    (r"§§ (\d+) et (\d+)", r"odst. \1 a \2"),
    (r"\b(\d+) bis bis\b", r"\1aa"),
    (r"\b(\d+) ter\b", r"\1b"),
    (r"\b([a-z]) bis\b", r"\1a"),
    (r"[Aa]près le alinéa (\d+)", r"za pododstavcem \1"),
    (r"[Aa]près l'article (\d+)", r"za článkem \1"),
    (r"[Aa]vant l'article (\d+)", r"před článkem \1"),
    (r"[Aa]près le sous-point ([a-z]{1,4}|\d+)\b", r"za podbodem \1"),
    (r"sous-point ([a-z]{1,4}|\d+)\b", r"podbod \1"),
    (r"[Aa]près le tiret (\d+)", r"za odrážkou \1"),
    (r"[Tt]iret (\d+)", r"odrážka \1"),
    (r"[Aa]près l'alinéa (\d+)", r"za pododstavcem \1"),
    (r"Annexe ([IVX]+)", r"příloha \1"),
    (r"^Annexe\b", "příloha"),
    (r"[Aa]près le paragraphe (\d+)", r"za odstavcem \1"),
    (r"[Aa]rticle (\d+) bis", r"článek \1a"),
    (r"nº ", "č. "),
    (r"§ ?(\d+) bis", r"§ \1a"),
    (r"\b(\d+|[A-Z]{1,3}) bis\b", r"\1a"),
    (r"partie introductive", "úvodní část"),
    (r"[Aa]près le point (\d+)", r"za bodem \1"),
    (r"[Aa]vant le point (\d+)", r"před bodem \1"),
    (r"[Aa]près le point ([a-z]{1,4})\b", r"za písm. \1"),
    (r"[Aa]vant le point ([a-z]{1,3})\b", r"před písm. \1"),
    (r"Article (\d+)", r"článek \1"),
    (r"après le § (\d+)", r"za odst. \1"),
    (r"Après le § ?(\d+a?)", r"za odst. \1"),
    (r"[Aa]vant le § (\d+)", r"před odst. \1"),
    (r"[Pp]aragraphe (\d+)", r"odstavec \1"),
    (r"alinéa (\d+)", r"pododstavec \1"),
    (r"points ([a-z]\)) et ([a-z]\))", r"písm. \1 a \2"),
    (r"point ([a-z]\))", r"písm. \1"),
    (r"point ([–-]?\d+)", r"bod \1"),
    (r"point ([a-z]{1,4})\b", r"písm. \1"),
    (r"\bet\b", "a"),
    (r"§ (\d+)", r"odst. \1"),
]
ORDINAL_M = {"premier": "první", "deuxième": "druhý", "troisième": "třetí", "quatrième": "čtvrtý", "cinquième": "pátý"}
# Části dělených hlasování: „§ 7/2“ -> „odst. 7, 2. část“; „Am 4/1“ -> „PN 4, 1. část“.
SPLIT = re.compile(r"(úvodní část|odst\. \d+|bod odůvodnění \w+|PN \d+|písm\. \w+|bod \d+|doporučení \d+|pododstavec)/(\d+)")
AMEND = re.compile(r"\bAm (\d+)")
FRENCH = re.compile(
    r"\b(le|la|les|du|des|de|et|sur|après|avant|considérant|amendements?|proposition|projet|vote|demande|"
    r"règlement|directive|annexe|article|alinéa|paragraphe|points?|tiret|bis|groupe|décharge|"
    r"recommandation|ligne|directrice|partie|introductive|deuxième|premier|sous|commission|conseil|"
    r"ensemble|texte|résolution|concernant|correspond|rejet|accord|dans|par|pour|aux?)\b",
    re.I,
)


def translate(description: str | None) -> str | None:
    if not description:
        return None
    s = description.strip()
    for pat, rep in PHRASES:
        s = re.sub(pat, rep, s)
    for pat, rep in PLACES:
        s = re.sub(pat, rep, s)
    s = AMEND.sub(r"PN \1", s)
    s = SPLIT.sub(lambda m: f"{m.group(1)}, {m.group(2)}. část", s)
    # zkratky velkými písmeny (bod odůvodnění AU, BCAE) nejsou francouzská slova
    if FRENCH.search(re.sub(r"\b[A-Z]{2,}\b|písm\. \w+", "", s)):
        return None
    return s[0].upper() + s[1:] if s else None
