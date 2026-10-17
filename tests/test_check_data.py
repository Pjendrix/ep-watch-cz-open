import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_data as cd  # noqa: E402


def write_state(d: Path, months, meps):
    (d / "votes").mkdir(parents=True)
    (d / "votes" / "index.json").write_text(json.dumps({"months": [{"month": m, "votes": n} for m, n in months]}))
    (d / "meps.json").write_text(json.dumps({"meps": meps}))


def mep(i, start="2024-07-16", end=None):
    return {"id": i, "name": f"MOCK {i}", "mandates": [{"start": start, "end": end}]}


@pytest.fixture
def states(tmp_path):
    prev, new = tmp_path / "prev", tmp_path / "new"
    write_state(prev, [("2024-07", 10), ("2024-09", 20)], [mep(1), mep(2), mep(3, end="2024-12-31")])
    return prev, new


def test_ok(states):
    prev, new = states
    write_state(new, [("2024-07", 10), ("2024-09", 20), ("2024-10", 5)], [mep(1), mep(2), mep(3, end="2024-12-31")])
    assert cd.check(prev, new, "2025-01-15", seats=2) == ([], [])


def test_first_run_without_prev(tmp_path):
    new = tmp_path / "new"
    write_state(new, [("2024-07", 10)], [mep(1), mep(2)])
    assert cd.check(None, new, "2025-01-15", seats=2) == ([], [])


def test_detects_all_problems(states):
    prev, new = states
    write_state(new, [("2024-09", 21)], [mep(1)])  # červenec zmizel, celkem 21 < 30, chybí 2 a 3
    problems, warnings = cd.check(prev, new, "2025-01-15", seats=3)
    assert any("aktivních poslanců" in p and "je 1" in p for p in problems)  # o 2 méně = chyba
    assert any("klesl z 30 na 21" in p for p in problems)
    assert any("zmizely měsíce: 2024-07" in p for p in problems)
    assert any("zmizeli poslanci" in p and "[2, 3]" in p for p in problems)


def test_active_count_respects_mandate_dates(states):
    prev, new = states
    write_state(new, [("2024-07", 10), ("2024-09", 20)], [mep(1), mep(2), mep(3, end="2024-12-31")])
    # do konce roku 2024 je mandát i u poslance 3 -> 3 aktivní místo 2
    assert any("je 3" in p for p in cd.check(prev, new, "2024-12-31", seats=2)[0])  # víc = chyba


def test_one_vacant_seat_is_only_warning(states, capsys):
    prev, new = states
    write_state(new, [("2024-07", 10), ("2024-09", 20)], [mep(1), mep(2), mep(3, end="2024-12-31")])
    problems, warnings = cd.check(prev, new, "2025-01-15", seats=3)
    assert problems == [] and len(warnings) == 1 and "je 2" in warnings[0]
    assert cd.main(["--prev", str(prev), "--data", str(new), "--today", "2025-01-15"]) == 1  # 21 míst, 2 aktivní


def test_main_exit_code(states):
    prev, new = states
    write_state(new, [("2024-09", 1)], [mep(1)])
    assert cd.main(["--prev", str(prev), "--data", str(new), "--today", "2025-01-15"]) == 1


def test_logo_warnings(tmp_path):
    import check_data as cd

    public, data = tmp_path / "public", tmp_path / "data"
    (public / "assets").mkdir(parents=True)
    data.mkdir()
    (public / "assets" / "ok.svg").write_text("<svg><path d='M0 0'/></svg>", encoding="utf-8")
    (public / "assets" / "bad.svg").write_text("<svg onload='x()'><a href='https://example.test'/></svg>", encoding="utf-8")
    (public / "assets" / "big.png").write_bytes(b"0" * 70_000)
    (data / "groups.json").write_text(
        json.dumps(
            [
                {"code": "A", "logo": "assets/ok.svg", "logo_source": "MOCK"},
                {"code": "B", "logo": "assets/bad.svg", "logo_source": "MOCK"},
                {"code": "C", "logo": "assets/big.png", "logo_source": None},
            ]
        ),
        encoding="utf-8",
    )
    w = " | ".join(cd.check_logos(data, public))
    assert "A" not in [x.split()[1] for x in cd.check_logos(data, public)]
    assert "SVG assets/bad.svg" in w and "70 kB" in w and "C (assets/big.png) nemá" in w


def test_delegations_checked(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    assert cd.check_delegations(d) == ([], [])  # chybí soubor: starší data, nic se nehlásí
    (d / "delegations.json").write_text(json.dumps({"own": "CZE", "peers": [], "countries": {}}))
    assert cd.check_delegations(d)[0] == ["delegations.json: chybí česká delegace"]
    own = {"seats": 21, "unity": [5, 10]}
    (d / "delegations.json").write_text(json.dumps({"own": "CZE", "peers": ["AAA"], "countries": {"CZE": own}}))
    (d / "stats.json").write_text(json.dumps({"votes_analysis": {"unity": {"united": 4, "considered": 10}}}))
    problems, warnings = cd.check_delegations(d)
    assert not problems and len(warnings) == 1 and "liší" in warnings[0]


def test_speeches_checked(tmp_path):
    prev, new = tmp_path / "prev", tmp_path / "new"
    prev.mkdir()
    new.mkdir()
    assert cd.check_speeches(prev, new) == []  # soubory chybí
    (prev / "speeches.json").write_text(json.dumps({"meps": {"1": [{"id": "a"}, {"id": "b"}], "2": []}}))
    (new / "speeches.json").write_text(json.dumps({"meps": {"1": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "2": []}}))
    assert cd.check_speeches(prev, new) == []
    (new / "speeches.json").write_text(json.dumps({"meps": {"1": [], "2": []}}))
    problems = cd.check_speeches(prev, new)
    assert any("klesl" in p for p in problems) and any("poslanec 1" in p for p in problems)


def test_attendance_checked(tmp_path):
    prev, new = tmp_path / "prev", tmp_path / "new"
    prev.mkdir()
    new.mkdir()
    assert cd.check_attendance(prev, new) == []
    (prev / "attendance.json").write_text(
        json.dumps({"days": [{"date": "2025-01-01", "attendees": 5}, {"date": "2025-01-02", "attendees": 5}]})
    )
    (new / "attendance.json").write_text(
        json.dumps({"days": [{"date": "2025-01-01", "attendees": 5}, {"date": "2025-01-02", "attendees": 0}]})
    )
    problems = cd.check_attendance(prev, new)
    assert any("prázdná" in p for p in problems) and not any("klesl" in p for p in problems)
    (new / "attendance.json").write_text(json.dumps({"days": [{"date": "2025-01-01", "attendees": 5}]}))
    assert any("klesl" in p for p in cd.check_attendance(prev, new))
