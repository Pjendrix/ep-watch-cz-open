import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from vote_kinds import classify, is_final, kind_of  # noqa: E402


def v(description, is_main=False, subject=None, amendment_number=None, title=None):
    return {"description": description, "is_main": is_main, "amendment_subject": subject,
            "amendment_number": amendment_number, "title": title}


# Vzory z aktuálních dat HowTheyVote (description, is_main, amendment_subject) -> (typ, inverted).
CASES = [
    (v("Proposition de résolution (ensemble du texte)", True), ("final", False)),
    (v("Proposition de résolution", True), ("final", False)),
    (v("Proposition de resolution", True), ("final", False)),
    (v("Proposition de la Commission", True), ("final", False)),
    (v("Proposition de la Commission au Conseil", True), ("final", False)),
    (v("Proposition de la Commission et amendements", True), ("final", False)),
    (v("Projet de décision du Conseil", True), ("final", False)),
    (v("Projet de règlement du Conseil", True), ("final", False)),
    (v("Projet du Conseil", True), ("final", False)),
    (v("Projet commun", True), ("final", False)),
    (v("Proposition de décision", True), ("final", False)),
    (v("Proposition de décision (ensemble du texte)", True), ("final", False)),
    (v(None, True), ("final", False)),
    # AGILE 197360: prozatímní dohoda
    (v("Accord provisoire - Am 2", True, "Provisional agreement"), ("provisional_agreement", False)),
    # AGILE 197601, A10-0176/2025 179804: návrh na zamítnutí
    (v("Proposition de rejet - Am 5", True, "Proposal for rejection"), ("rejection", True)),
    (v("Proposition de rejet", True), ("rejection", True)),
    (v("Proposition de rejet - Am 3= 4=", True), ("rejection", True)),
    (v("Proposition de rejet de la position du Conseil - Am 1", True), ("rejection", True)),
    (v("Décision d'engager des négociations interinstitutionnelles", True), ("mandate", False)),
    (v("Demande de décision d'urgence", True), ("urgency", False)),
    (v("Après le § 1 - Am 1", False, "After § 1"), ("amendment", False)),
    (v("§ 1 - Am 4", False, "§ 1", "§ 1"), ("amendment", False)),
    (v("Après le considérant D - Am 1"), ("amendment", False)),
    (v("Avant le § 1 - Am 3"), ("amendment", False)),
    (v("Amendements de la commission compétente - vote séparé - Am 1/2"), ("amendment", False)),
    (v("Article 1 - alinéa 1 - point 2; Règlement (UE) 2021/1119 - Article 4 - paragraphe 3 - Am 64S"),
     ("amendment", False)),
    (v("§ 5/1", False, "§ 5", "§ 5/1"), ("split_part", False)),
    (v("Considérant R/2"), ("split_part", False)),
    (v("Annexe, partie introductive/2"), ("split_part", False)),
    (v(None, False, None, "12"), ("amendment", False)),
    (v(None), ("other", False)),
    (v("Demande d'ajournement du vote"), ("procedural", False)),
    (v("Demande de renvoi en commission"), ("procedural", False)),
    # námitky proti aktům Komise (169418, 181956): hlavní hlasování = objection, PN k nim zůstávají PN
    (v("Proposition de résolution", True, title="Objection pursuant to Rule 115(2) and (3), and Rule 115(4)(c): MOCK"),
     ("objection", False)),
    (v("Proposition de résolution (ensemble du texte)", True, title="Objection pursuant to Rule 114(3): MOCK"),
     ("objection", False)),
    (v("Après le § 2 - Am 2", False, "After § 2", title="Objection pursuant to Rule 115(2) and (3): MOCK"),
     ("amendment", False)),
    (v("Proposition de décision du Conseil"), ("other", False)),
]


@pytest.mark.parametrize("vote,expected", CASES)
def test_classify(vote, expected):
    assert classify(vote) == expected


def test_kind_of_prefers_stored_value_and_is_final():
    assert kind_of({"vote_kind": "mandate", "is_main": True, "description": None}) == "mandate"
    assert is_final(v("Accord provisoire - Am 2", True))
    assert not is_final(v("Proposition de rejet", True))
    assert not is_final(v("Demande de décision d'urgence", True))
    assert is_final(v("Proposition de résolution", True, title="Objection pursuant to Rule 115(2): MOCK"))
