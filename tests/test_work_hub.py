import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import work_hub as wh  # noqa: E402

MEPS = [
    {"id": 1, "mandates": [{"start": "2024-07-16", "end": None}]},
    {"id": 2, "mandates": [{"start": "2024-07-16", "end": "2025-06-30"}]},
]
INFO = {1: {"group": {"code": "EPP", "short_label": "EPP"}}, 2: {"group": {"code": "EPP", "short_label": "EPP"}}}


def item(i, typ, status="no_vote", vote_id=None, date="2025-03-01", proc="COD", role="RAPPORTEUR"):
    return {
        "id": i,
        "label": f"L-{i}",
        "date": date,
        "title": {"cs": f"Text {i}", "en": None},
        "type": typ,
        "role": role,
        "status": status,
        "vote_id": vote_id,
        "vote_date": "2025-04-01" if vote_id else None,
        "process_type": proc,
        "legislative": proc == "COD",
    }


OWN = {
    "source": {"name": "MOCK"},
    "updated": "2025-10-01",
    "complete": True,
    "meps": {
        "1": {
            "items": [
                item("r1", "report", "ADOPTED", 11),
                item("r2", "report", "REJECTED"),
                item("s1", "shadow_report", "ADOPTED", 12, proc="INI"),
                item("q1", "question", date="2025-02-10"),
                item("q2", "question", date="2025-02-20"),
            ]
        },
        # druhý Čech na stejném textu r1 jako stínový: text se v součtech počítá jednou, role se sloučí
        "2": {"items": [item("r1", "shadow_report", "ADOPTED", 11), item("q1", "question", date="2025-02-10")]},
    },
}
SPEECHES = {
    "meps": {
        "1": [
            {"id": "a", "date": "2025-02-05", "type": "speech", "minutes": 1.5, "item": "x"},
            {"id": "b", "date": "2025-02-06", "type": "written_statement", "minutes": None, "item": "x"},
        ],
        "2": [{"id": "c", "date": "2025-09-01", "type": "speech", "minutes": 1.0, "item": "y"}],
    }
}  # 2 už není v mandátu
ATT = {
    "days": [
        {"date": "2025-02-05", "attendees": 600, "present": [1, 2], "excused": []},
        {"date": "2025-09-01", "attendees": 600, "present": [1], "excused": []},
    ]
}


def hub():
    return wh.build_work_hub(OWN, MEPS, INFO, SPEECHES, ATT)


def test_texts_counted_once_even_with_two_czech_roles():
    t = hub()["totals"]
    assert t["reports_lead"] == 2 and t["reports_shadow"] == 2  # r1, r2 vede; r1, s1 stínový
    assert t["reports_adopted"] == 2 and t["questions"] == 2  # r1, s1 přijato; q1 má dva autory, počítá se jednou


def test_speeches_and_presence_only_in_mandate():
    t = hub()["totals"]
    assert t["speeches"] == 1 and t["speeches_minutes"] == 2 and t["written_statements"] == 1  # projev poslance 2 po mandátu se nepočítá
    assert t["presence"] == [3, 3]  # den 1: oba, den 2: jen poslanec 1


def test_timeline_by_process_group_and_recent():
    h = hub()
    assert {x["month"]: (x["speeches"], x["questions"]) for x in h["timeline"]} == {"2025-02": (1, 2)}
    cod = next(r for r in h["by_process"] if r["process_type"] == "COD")
    assert cod["reports_lead"] == 2 and cod["reports_shadow"] == 1 and cod["adopted"] == 1 and cod["legislative"]
    assert h["by_group"] == [
        {
            "code": "EPP",
            "short_label": "EPP",
            "meps": 2,
            "reports_lead": 2,
            "reports_shadow": 2,
            "opinions": 0,
            "questions": 3,
            "speeches": 1,
        }
    ]  # součty rolí po poslancích (q1 u obou)
    assert [r["vote_id"] for r in h["recent_adopted"]] == [12, 11]  # nejnovější hlasování první
    r11 = next(r for r in h["recent_adopted"] if r["vote_id"] == 11)
    assert r11["lead"] == [1] and r11["shadow"] == [2]


def test_no_ranking_keys():
    assert "rank" not in str(hub()) and "score" not in str(hub())
