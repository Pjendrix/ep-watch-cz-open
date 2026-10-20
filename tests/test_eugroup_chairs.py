"""Předsedové politických skupin z EP API (F1b, zadání 20. 10. 2026): role, období, pohlaví, prázdná odpověď."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_group_chairs as fgc  # noqa: E402

GROUP = "def/ep-entities/EU_POLITICAL_GROUP"


def ms(org, role, start, end=None, cls=GROUP):
    period = {"startDate": start, **({"endDate": end} if end else {})}
    return {"organization": org, "role": role, "membershipClassification": cls, "memberDuring": period}


def person(pid, given, family, gender, memberships):
    return {
        "identifier": str(pid),
        "label": f"{given} {family.upper()}",
        "givenName": given,
        "familyName": family,
        "hasGender": f"http://publications.europa.eu/resource/authority/human-sex/{gender}" if gender else None,
        "hasMembership": memberships,
    }


CURRENT = [
    {"identifier": "1", "api:country-of-representation": "DE"},
    {"identifier": "2", "api:country-of-representation": "FR"},
    {"identifier": "3", "api:country-of-representation": "PL"},
    {"identifier": "4", "api:country-of-representation": "IT"},
]
ORGS = {"org/9001": "EPP", "org/9002": "ECR"}


def test_chair_and_co_chairs_with_period_and_gender():
    details = [
        person(1, "MOCK_Anna", "Alfa", "FEMALE", [ms("org/9001", "def/ep-roles/CHAIR", "2024-07-16")]),
        person(2, "MOCK_Bert", "Beta", None, [ms("org/9002", "def/ep-roles/CHAIR_CO", "2024-07-16")]),
        person(3, "MOCK_Cyril", "Gama", "MALE", [ms("org/9002", "def/ep-roles/CHAIR_CO", "2025-01-01")]),
        # skončené předsednictví, místopředseda a předseda výboru se nepočítají
        person(
            4,
            "MOCK_Dan",
            "Delta",
            "MALE",
            [
                ms("org/9002", "def/ep-roles/CHAIR_CO", "2024-07-16", "2024-12-31"),
                ms("org/9001", "def/ep-roles/CHAIR_VICE", "2024-07-16"),
                ms("org/5555", "def/ep-roles/CHAIR", "2024-07-16", cls="def/ep-entities/COMMITTEE_PARLIAMENTARY_STANDING"),
            ],
        ),
    ]
    out = fgc.chairs_from(CURRENT, details, ORGS, "2026-10-20")
    assert out["EPP"] == [{"mep_id": 1, "name": "MOCK_Anna Alfa", "country": "DE", "role": "CHAIR", "gender": "F", "start": "2024-07-16"}]
    assert [(c["name"], c["gender"]) for c in out["ECR"]] == [("MOCK_Bert Beta", None), ("MOCK_Cyril Gama", "M")]


def test_empty_api_answer_gives_empty_list_never_invented():
    out = fgc.chairs_from(CURRENT, [person(1, "MOCK_Anna", "Alfa", "FEMALE", [])], ORGS, "2026-10-20")
    assert out == {"ECR": [], "EPP": []}


def test_every_known_group_is_mapped():
    import json

    import pytest

    path = ROOT / "data" / "groups.json"
    if not path.exists():
        pytest.skip("data/groups.json není (veřejný export)")
    groups = json.loads(path.read_text(encoding="utf-8"))
    assert {g["code"] for g in groups} - {"NI"} <= set(fgc.EP_TO_CODE.values())
