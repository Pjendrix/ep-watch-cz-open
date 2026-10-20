"""Složení frakcí podle zemí (F1a, zadání 20. 10. 2026): součty, řazení, číselník zemí, čitelné chyby."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_web as bw  # noqa: E402
import group_countries as gc  # noqa: E402

ISO2 = {"DEU": "DE", "CZE": "CZ", "FRA": "FR", "POL": "PL"}
VOTES = [
    {"id": 1, "timestamp": "2026-10-07T12:00:00", "total": 3},
    {"id": 2, "timestamp": "2026-10-08T12:00:00", "total": 5},
    {"id": 3, "timestamp": "2026-10-08T12:30:00", "total": 5},
]
# Poslanec 11 přešel během dne z EPP do PFE: platí řádek z posledního hlasování dne (3). Hlasování 1 je z jiného dne.
ROWS = [
    (1, 99, "POL", "ECR"),
    (2, 10, "DEU", "EPP"),
    (2, 11, "CZE", "EPP"),
    (2, 12, "FRA", "PFE"),
    (2, 13, "CZE", "NI"),
    (2, 14, "DEU", "EPP"),
    (3, 10, "DEU", "EPP"),
    (3, 11, "CZE", "PFE"),
    (3, 12, "FRA", "PFE"),
    (3, 13, "CZE", "NI"),
    (3, 14, "DEU", "EPP"),
]


def test_composition_last_day_last_row():
    out = gc.composition(VOTES, ROWS, ISO2)
    assert out["as_of"] == "2026-10-08" and out["vote_id"] == 3 and out["members"] == 5
    assert out["groups"]["EPP"] == {"seats": 2, "n_countries": 1, "by_country": [{"cc": "DE", "n": 2}]}
    assert out["groups"]["PFE"]["by_country"] == [{"cc": "CZ", "n": 1}, {"cc": "FR", "n": 1}]  # shoda: podle cc
    assert "ECR" not in out["groups"]  # hlasování 1 je z jiného dne
    assert sum(g["seats"] for g in out["groups"].values()) == out["members"]


def test_sorting_is_deterministic():
    a = gc.composition(VOTES, ROWS, ISO2)
    b = gc.composition(VOTES, list(reversed(ROWS)), ISO2)
    assert a == b


def test_count_mismatch_is_readable_error():
    with pytest.raises(gc.CompositionError, match="hlasů"):
        gc.composition([{**v, "total": 6} if v["id"] == 3 else v for v in VOTES], ROWS, ISO2)


def test_unknown_country_is_error():
    with pytest.raises(gc.CompositionError, match="countries_cs"):
        gc.composition(VOTES, [*ROWS[:-1], (3, 14, "XXX", "EPP")], {**ISO2})


def test_every_country_in_data_has_czech_name():
    doc = json.loads((ROOT / "data" / "manual" / "countries_cs.json").read_text(encoding="utf-8"))
    assert len(doc["countries"]) == 27
    iso2 = gc.iso3_to_iso2(doc)
    comp_path = ROOT / "data" / "group_countries.json"
    if comp_path.exists():
        comp = json.loads(comp_path.read_text(encoding="utf-8"))
        assert sum(g["seats"] for g in comp["groups"].values()) == comp["members"]
        for g in comp["groups"].values():
            assert {c["cc"] for c in g["by_country"]} <= set(doc["countries"])
            assert g["by_country"] == sorted(g["by_country"], key=lambda c: (-c["n"], c["cc"]))
    assert iso2["CZE"] == "CZ"


def test_missing_column_is_readable_error(tmp_path):
    import fetch_votes as fv

    with pytest.raises(fv.FormatError, match="country_code"):
        fv.check_columns(["vote_id", "member_id", "position", "group_code"], "member_votes")


def test_membership_state_current_and_former():
    open_mandate = [{"start": "2024-07-16", "end": None}]
    assert bw.membership_state(open_mandate, [{"start": "2024-07-16", "end": None}], "2026-10-08") == {"current": True, "end": None}
    assert bw.membership_state(open_mandate, [{"start": "2024-07-16", "end": "2026-02-03"}], "2026-10-08") == {
        "current": False,
        "end": "2026-02-03",
    }
    closed = [{"start": "2024-07-16", "end": "2025-07-30"}]
    assert bw.membership_state(closed, [{"start": "2024-07-16", "end": None}], "2026-10-08") == {"current": False, "end": "2025-07-30"}
