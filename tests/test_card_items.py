"""Strany se jmény pro kartu hlasování (vote_parties.card_items, zadání 20. 10. 2026, K1)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import vote_parties as vp  # noqa: E402

PARTIES = [
    {"id": 1, "short_label": "MOCK A", "independent": False, "logo": "assets/logos/cz/1.svg", "logo_aspect": 2.0, "chart_color": "#111111"},
    {"id": 9, "short_label": "Ind.", "independent": True},
]
GROUPS = [{"code": "EPP", "ep_code": "PPE", "short_label": "EPP"}, {"code": "NI", "short_label": "nezařazení"}]


def mep(i, family, gender="MALE", given="Jan"):
    return {
        "id": i,
        "name": f"{given} {family.upper()}",
        "given_name": given,
        "family_name": family,
        "sort_label": family.upper(),
        "gender": gender,
    }


MEPS = {
    1: mep(1, "Novák"),
    2: mep(2, "Novák", given="Petr"),
    3: mep(3, "Adam"),
    4: mep(4, "Bílá", "FEMALE", "Eva"),
    5: mep(5, "Černý", None),
}


def pos(i, position, party, group="EPP"):
    return {"member_id": i, "position": position, "national_party_id": party, "group_code": group}


def test_parties_names_order_and_independents():
    cz = [pos(1, "AGAINST", 1), pos(2, "FOR", 1), pos(3, "FOR", 1), pos(4, "FOR", 9, "NI"), pos(5, "DID_NOT_VOTE", 9, "NI")]
    items = vp.card_items(cz, MEPS, PARTIES, GROUPS)
    assert [i["label"] for i in items] == ["MOCK A", "nezávislá", "nezávislý poslanec"]
    a = items[0]
    assert a["partyId"] == 1 and a["logo"] == "assets/logos/cz/1.svg" and a["group"] == "EPP"
    # podle hlasu (pro → proti), uvnitř podle sort_label; shodná příjmení s iniciálou
    assert [(m["surname"], m["position"]) for m in a["members"]] == [("Adam", "FOR"), ("P. Novák", "FOR"), ("J. Novák", "AGAINST")]
    assert a["positions"] == ["FOR", "FOR", "AGAINST"]
    assert items[1]["independent"] and items[1]["logo"] is None and items[1]["group"] == "nezařazení"


def test_every_member_exactly_once():
    cz = [pos(i, "FOR", 1) for i in (1, 2, 3)] + [pos(4, "ABSTENTION", 9, "NI")]
    items = vp.card_items(cz, MEPS, PARTIES, GROUPS)
    assert sorted(m["id"] for it in items for m in it["members"]) == [1, 2, 3, 4]
