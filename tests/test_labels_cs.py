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
    ("Amendements de la commission compétente - vote séparé - Am 1/2",
     "Pozměňovací návrhy příslušného výboru - oddělené hlasování - PN 1, 2. část"),
    ("Amendements de la commission compétente - votes séparés - Am 1/2",
     "Pozměňovací návrhy příslušného výboru - oddělená hlasování - PN 1, 2. část"),
    ("Article 1 - alinéa 1 - point 2; Règlement (UE) 2021/1119 - Article 4 - paragraphe 3 - Am 64S",
     "Článek 1 - pododstavec 1 - bod 2; nařízení (EU) 2021/1119 - článek 4 - odstavec 3 - PN 64S"),
    ("Après le §5 bis - Am 2", "Za odst. 5a - PN 2"),
    ("§ 4, après le tiret 2 - Am 7", "Odst. 4, za odrážkou 2 - PN 7"),
    ("Demande de renvoi (article 200, paragraphe 2, du règlement)",
     "Žádost o vrácení (čl. 200 odst. 2 jednacího řádu)"),
    ("Annexe I - point 3 - sous-point b; Règlement (UE) nº 1/2020",
     "Příloha I - bod 3 - podbod b; nařízení (EU) č. 1/2020"),
]


@pytest.mark.parametrize("fr,cs", CASES)
def test_translate(fr, cs):
    assert translate(fr) == cs


@pytest.mark.parametrize("fr", ["Demande d'ajournement du groupe The Left",
                                "Proposition de décision concernant la décharge (Frontex)",
                                "Annexe, recommandation 1/2"])
def test_unknown_keeps_original(fr):
    assert translate(fr) is None  # nikdy polopřeklad


def test_empty():
    assert translate(None) is None and translate("") is None
