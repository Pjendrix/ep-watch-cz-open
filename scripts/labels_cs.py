"""Český popis hlasování z francouzského pole description (HowTheyVote), podle pravidel.

Žádná AI: postupné nahrazení známých výrazů. Když po překladu zůstane francouzské slovo,
vrací None a web ukáže originál (nikdy polopřeklad).
"""

from __future__ import annotations

import re

# Celé fráze (pořadí je důležité: delší dřív).
PHRASES = [
    (r"\(correspond à l'article (\d+) dans l'amendement (\d+)\)", r"(odpovídá článku \1 v PN \2)"),
    (r"Demande de renvoi \(article (\d+), paragraphe (\d+), du règlement\)",
     r"žádost o vrácení (čl. \1 odst. \2 jednacího řádu)"),
    (r"Abrogation de la ", "zrušení "),
    (r"Proposition de résolution de remplacement", "alternativní návrh usnesení"),
    (r"Proposition de résolution commune", "společný návrh usnesení"),
    (r"Proposition de r[ée]solution", "návrh usnesení"),
    (r"Proposition de la Commission et amendements", "návrh Komise a pozměňovací návrhy"),
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
    (r"votes séparés et votes par division", "oddělená a dělená hlasování"),
    (r"votes séparés", "oddělená hlasování"),
    (r"vote séparé", "oddělené hlasování"),
    (r"ensemble du texte", "celý text"),
    (r"Procédure d'approbation", "postup souhlasu"),
]
# Odkazy na místo v textu.
PLACES = [
    (r"Après le considérant ([A-Z]{1,3}|\d+)", r"za bodem odůvodnění \1"),
    (r"Avant le considérant ([A-Z]{1,3}|\d+)", r"před bodem odůvodnění \1"),
    (r"Considérant ([A-Z]{1,3}|\d+)", r"bod odůvodnění \1"),
    (r"Après le visa (\d+)", r"za právním východiskem \1"),
    (r"Visa (\d+)", r"právní východisko \1"),
    (r"Règlement \(UE\) (nº |č\. )?(\d+/\d+)", r"nařízení (EU) \1\2"),
    (r"Directive \(UE\) (nº |č\. )?(\d+/\d+)", r"směrnice (EU) \1\2"),
    (r"[Aa]près l'article (\d+)", r"za článkem \1"),
    (r"[Aa]vant l'article (\d+)", r"před článkem \1"),
    (r"[Aa]près le sous-point ([a-z]{1,4})\b", r"za podbodem \1"),
    (r"sous-point ([a-z]{1,4})\b", r"podbod \1"),
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
    (r"[Aa]près le point ([a-z]{1,3})\b", r"za písm. \1"),
    (r"[Aa]vant le point ([a-z]{1,3})\b", r"před písm. \1"),
    (r"Article (\d+)", r"článek \1"),
    (r"après le § (\d+)", r"za odst. \1"),
    (r"Après le § ?(\d+a?)", r"za odst. \1"),
    (r"Avant le § (\d+)", r"před odst. \1"),
    (r"paragraphe (\d+)", r"odstavec \1"),
    (r"alinéa (\d+)", r"pododstavec \1"),
    (r"point (\d+)", r"bod \1"),
    (r"point ([a-z]{1,3})\b", r"písm. \1"),
    (r"§ (\d+)", r"odst. \1"),
]
# Části dělených hlasování: „§ 7/2“ -> „odst. 7, 2. část“; „Am 4/1“ -> „PN 4, 1. část“.
SPLIT = re.compile(r"(úvodní část|odst\. \d+|bod odůvodnění \w+|PN \d+|písm\. \w+|bod \d+)/(\d+)")
AMEND = re.compile(r"\bAm (\d+)")
FRENCH = re.compile(r"\b(le|la|les|du|des|de|et|sur|après|avant|considérant|amendements?|proposition|projet|vote|demande|"
                    r"règlement|directive|annexe|article|alinéa|paragraphe|points?|tiret|bis|groupe|décharge|"
                    r"recommandation|ligne|directrice|partie|introductive|deuxième|premier|sous|commission|conseil|"
                    r"ensemble|texte|résolution|concernant|correspond|rejet|accord|dans|par|pour|aux?)\b", re.I)


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
    if FRENCH.search(s):
        return None
    return s[0].upper() + s[1:] if s else None
