import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from labels_cs import translate  # noqa: E402

# Nejčastější vzory z aktuálních dat HowTheyVote.
CASES = [
    ("Proposition de résolution (ensemble du texte)", "Návrh usnesení (celý text)"),
    ("Proposition de résolution", "Návrh usnesení"),
    ("Proposition de résolution commune", "Společný návrh usnesení"),
    ("Proposition de la Commission", "Návrh Komise"),
    ("Projet de décision du Conseil", "Návrh rozhodnutí Rady"),
    ("Accord provisoire - Am 2", "Prozatímní dohoda - PN 2"),
    ("Proposition de rejet - Am 5", "Návrh na zamítnutí - PN 5"),
    ("Décision d'engager des négociations interinstitutionnelles", "Rozhodnutí zahájit jednání s Radou"),
    ("Demande de décision d'urgence", "Žádost o naléhavý postup"),
    ("Demande d'ajournement du vote", "Žádost o odložení hlasování"),
    ("Après le § 1 - Am 1", "Za odst. 1 - PN 1"),
    ("Avant le § 1 - Am 3", "Před odst. 1 - PN 3"),
    ("§ 1 - Am 4", "Odst. 1 - PN 4"),
    ("§ 5/1", "Odst. 5, 1. část"),
    ("§ 10/2", "Odst. 10, 2. část"),
    ("Après le considérant D - Am 1", "Za bodem odůvodnění D - PN 1"),
    ("Considérant R/2", "Bod odůvodnění R, 2. část"),
    ("Visa 3", "Právní východisko 3"),
    (
        "Amendements de la commission compétente - vote séparé - Am 1/2",
        "Pozměňovací návrhy příslušného výboru - oddělené hlasování - PN 1, 2. část",
    ),
    (
        "Amendements de la commission compétente - votes séparés - Am 1/2",
        "Pozměňovací návrhy příslušného výboru - oddělená hlasování - PN 1, 2. část",
    ),
    (
        "Article 1 - alinéa 1 - point 2; Règlement (UE) 2021/1119 - Article 4 - paragraphe 3 - Am 64S",
        "Článek 1 - pododstavec 1 - bod 2; nařízení (EU) 2021/1119 - článek 4 - odstavec 3 - PN 64S",
    ),
    ("Après le §5 bis - Am 2", "Za odst. 5a - PN 2"),
    ("§ 4, après le tiret 2 - Am 7", "Odst. 4, za odrážkou 2 - PN 7"),
    ("Demande de renvoi (article 200, paragraphe 2, du règlement)", "Žádost o vrácení (čl. 200 odst. 2 jednacího řádu)"),
    ("Annexe I - point 3 - sous-point b; Règlement (UE) nº 1/2020", "Příloha I - bod 3 - podbod b; nařízení (EU) č. 1/2020"),
    # vzory doplněné 25. 10. 2026 (dříve zůstávaly francouzsky)
    ("Demande d'ajournement du groupe The Left", "Žádost frakce The Left o odložení hlasování"),
    ("Proposition de décision concernant la décharge (Frontex)", "Návrh rozhodnutí o udělení absolutoria (Frontex)"),
    ("Annexe, recommandation 1/2", "Příloha, doporučení 1, 2. část"),
    ("Recommandation n° 3, cinquième alinéa/2", "Doporučení č. 3, pátý pododstavec, 2. část"),
    (
        "Amendements de la commission compétente - vote en bloc - Am 1-243",
        "Pozměňovací návrhy příslušného výboru - hromadné hlasování - PN 1-243",
    ),
    (
        "Amendements de la commission - votes séparés et votes par division - Am 39/2",
        "Pozměňovací návrhy výboru - oddělená a dělená hlasování - PN 39, 2. část",
    ),
    ("Considérant AU", "Bod odůvodnění AU"),
    ("§ 1, point au/2", "Odst. 1, písm. au, 2. část"),
    ("Article 4, après le alinéa 1 - Am 286", "Článek 4, za pododstavcem 1 - PN 286"),
    ("Annexe VII, partie C, point 13 - Am 371", "Příloha VII, část C, bod 13 - PN 371"),
    (
        "Article premier - alinéa 1 - point 3; Décision 89/367/CEE du Conseil - Article 2 - paragraphe 2 - après le point d - Am 22",
        "Článek 1 - pododstavec 1 - bod 3; rozhodnutí Rady 89/367/EHS - článek 2 - odstavec 2 - za písm. d - PN 22",
    ),
    (
        "Article 1 - alinéa 1 - point 1; Directive 2003/87/CE - Article 10 bis - après le paragraphe 2 ter - Am 14",
        "Článek 1 - pododstavec 1 - bod 1; směrnice 2003/87/ES - článek 10a - za odstavcem 2b - PN 14",
    ),
    ("Après l'article 4; Règlement (CE) nº 816/2006 - Am 1", "Za článkem 4; nařízení (ES) č. 816/2006 - PN 1"),
    (
        "Article 4 - alinéa 1 - point 8; Article 15 - deuxième phrase - Am 390",
        "Článek 4 - pododstavec 1 - bod 8; článek 15 - druhá věta - PN 390",
    ),
    ("§ 4, après le point 2, point 3 et après le point 3 - Am 9-14", "Odst. 4, za bodem 2, bod 3 a za bodem 3 - PN 9-14"),
]


@pytest.mark.parametrize("fr,cs", CASES)
def test_translate(fr, cs):
    assert translate(fr) == cs


@pytest.mark.parametrize(
    "fr",
    ["Proposition de règlement délégué", "Annexe, ligne 3 - vote final"],
)
def test_unknown_keeps_original(fr):
    assert translate(fr) is None  # nikdy polopřeklad


def test_empty():
    assert translate(None) is None and translate("") is None
