import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import group_stats as gs  # noqa: E402


def vote(i, counts, kind="final"):
    return {"id": i, "date": "2025-01-15", "vote_kind": kind, "is_main": kind == "final", "group_counts": counts}


def test_attendance_majority_and_splits():
    votes = [
        vote(1, {"AAA": [90, 10, 0, 20], "NI": [5, 5, 0, 0]}),  # menšina 10 %: nerozděleno
        vote(2, {"AAA": [50, 50, 0, 0]}, kind="amendment"),  # půl na půl: výrazně rozděleno
        vote(3, {"AAA": [3, 2, 0, 0]}),
    ]  # < 10 hlasujících: nepočítá se do soudržnosti
    s = gs.build_group_stats(votes)
    assert "NI" not in s
    a = s["AAA"]
    assert a["attendance"] == [100 + 100 + 5, 120 + 100 + 5]
    assert a["majority"] == [90 + 50, 100 + 100] and a["considered"] == 2
    assert a["splits"] == 1 and a["split_ids"] == [2]
    assert a["considered_main"] == 1 and a["splits_main"] == 0 and a["split_ids_main"] == []  # závěrečná: jen hlasování 1 a 3


def test_split_list_is_ordered_by_minority_and_limited():
    votes = [vote(i, {"AAA": [100 - i, i, 0, 0]}) for i in range(30, 51)]  # menšina roste s i
    ids = gs.build_group_stats(votes)["AAA"]["split_ids"]
    assert ids[0] == 50 and ids == sorted(ids, reverse=True) and len(ids) <= gs.SPLIT_LIMIT
