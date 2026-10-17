import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import attendance as at  # noqa: E402
import fetch_attendance as fa  # noqa: E402
from fetch_meps import FormatError  # noqa: E402

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "ep" / "meetings_MOCK.json").read_text(encoding="utf-8"))
CZ = {1, 2, 3}


def days():
    return [d for d in (fa.parse_day(i, CZ) for i in FIXTURE["data"]) if d]


def test_only_term_days_with_register_and_only_czech_ids():
    d = days()
    assert [x["date"] for x in d] == ["2024-09-16", "2024-09-17"]  # 2024-10-07 bez listiny, 2023 jiné období
    assert d[0] == {"date": "2024-09-16", "attendees": 4, "present": [1, 2], "excused": [3]}
    assert d[1]["present"] == [2] and d[1]["excused"] == [1]


def test_future_days_are_not_absence():
    assert fa.parse_day(FIXTURE["data"][0], CZ, today="2024-09-01") is None


def test_missing_field_is_format_error():
    with pytest.raises(FormatError):
        fa.parse_day({"id": "x"}, CZ)


def test_count_presence_in_mandate_and_excused_separately():
    m = [{"start": "2024-07-16", "end": None}]
    assert at.count_presence(days(), 1, m) == {"present": 1, "excused": 1, "days": 2}  # 17. 9. omluven, v listině nebyl
    assert at.count_presence(days(), 2, m) == {"present": 2, "excused": 0, "days": 2}
    assert at.count_presence(days(), 3, m) == {"present": 0, "excused": 1, "days": 2}  # 17. 9. ani omluven
    # mandát začíná po prvním dni: počítá se jen 17. 9.
    assert at.count_presence(days(), 2, [{"start": "2024-09-17", "end": None}]) == {"present": 1, "excused": 0, "days": 1}
    # v listině i mezi omluvenými = přítomen, ne omluven
    both = [{"date": "2024-09-16", "attendees": 1, "present": [1], "excused": [1]}]
    assert at.count_presence(both, 1, m) == {"present": 1, "excused": 0, "days": 1}
