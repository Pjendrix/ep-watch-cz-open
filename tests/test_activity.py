import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import activity as ac  # noqa: E402
import fetch_speeches as fs  # noqa: E402
from fetch_meps import FormatError  # noqa: E402

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "ep" / "speeches_MOCK.json").read_text(encoding="utf-8"))


def rows():
    return [r for r in (fs.parse_speech(i, 1) for i in FIXTURE["data"]) if r]


def test_parse_types_minutes_and_item():
    r = {x["id"]: x for x in rows()}
    assert r["MOCK-1"] == {"id": "MOCK-1", "date": "2024-09-18", "type": "speech", "minutes": 1.95, "item": "CRE-10-2024-09-18-ITM-002"}
    assert r["MOCK-3"]["type"] == "written_statement" and r["MOCK-3"]["minutes"] is None
    assert r["MOCK-2"]["minutes"] == 1.0


def test_other_person_or_role_is_skipped():
    item = {**FIXTURE["data"][0]}
    assert fs.parse_speech(item, 999) is None                                   # jiný poslanec
    other = {**item, "had_participation": {**item["had_participation"], "participation_role": "def/ep-roles/CHAIR"}}
    assert fs.parse_speech(other, 1) is None


def test_unknown_activity_type_is_format_error_not_silently_counted():
    item = {**FIXTURE["data"][0], "had_activity_type": "def/ep-activities/SOMETHING_NEW"}
    with pytest.raises(FormatError, match="SOMETHING_NEW"):
        fs.parse_speech(item, 1)


def test_missing_field_is_format_error():
    with pytest.raises(FormatError):
        fs.parse_speech({"id": "x", "activity_date": "2024-01-01"}, 1)


def test_count_only_in_mandate_and_written_statements_separate():
    # mandát 16. 7. 2024 – 31. 10. 2025: MOCK-4 (2023) a MOCK-5 (listopad 2025) jsou mimo
    c = ac.count_activity(rows(), [{"start": "2024-07-16", "end": "2025-10-31"}])
    assert c == {"speeches": 2, "speeches_minutes": 3.0, "speeches_timed": 2, "speech_items": 1, "written_statements": 1}
    all_time = ac.count_activity(rows(), [{"start": "2019-07-02", "end": None}])
    assert all_time["speeches"] == 4 and all_time["speeches_timed"] == 2 and all_time["written_statements"] == 1  # 2 projevy bez délky se počítají


def test_minutes_between_edge_cases():
    assert ac.minutes_between(None, "2024-01-01T10:00:00+01:00") is None
    assert ac.minutes_between("2024-01-01T10:05:00+01:00", "2024-01-01T10:00:00+01:00") is None
    assert ac.minutes_between("bad", "worse") is None
