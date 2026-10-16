import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import category_stats as cs  # noqa: E402

MEPS = {i: {"id": i, "mandates": [{"start": "2024-07-16", "end": None}]} for i in (1, 2, 3)}


def vote(i, codes, positions, kind="final", date="2025-01-15"):
    return {"id": i, "date": date, "vote_kind": kind, "is_main": kind == "final",
            "topics": {"oeil": [{"code": c, "label": "MOCK"} for c in codes]},
            "cz_positions": [{"member_id": m, "position": p} for m, p in positions]}


def test_votes_counted_into_every_category_and_untagged_separately():
    votes = [vote(1, ["6.10.02", "3.70.01"], [(1, "FOR"), (2, "FOR"), (3, "AGAINST")]),   # obrana + klima, rozdělení
             vote(2, ["3.70.01"], [(1, "FOR"), (2, "FOR"), (3, "DID_NOT_VOTE")], kind="amendment"),
             vote(3, [], [(1, "AGAINST"), (2, "AGAINST"), (3, "AGAINST")])]
    out = {r["key"]: r for r in cs.category_stats(votes, MEPS)["categories"]}
    assert out["def"]["votes"] == 1 and out["env"]["votes"] == 2 and out[cs.NONE_KEY]["votes"] == 1
    assert out["env"]["final"] == 1 and out["env"]["cz_final"] == [2, 1, 0, 0]
    assert out["def"]["cz_united_final"] == [0, 1]            # Češi se rozešli (2 pro, 1 proti)
    assert out[cs.NONE_KEY]["cz_united_final"] == [1, 1]      # všichni proti = jednotně
    assert out["env"]["cz_attendance"] == [5, 6]              # 3 + 2 hlasovali z 3 + 3 možných
    assert "tra" not in out                                   # prázdná kategorie se nevypíše


def test_mep_outside_mandate_is_not_counted():
    meps = {1: {"id": 1, "mandates": [{"start": "2024-07-16", "end": "2024-12-31"}]}}
    r = cs.category_stats([vote(1, ["3.70.01"], [(1, "FOR")])], meps)["categories"][0]
    assert r["cz_attendance"] == [0, 0]


def test_final_trace_counts_only_final_votes_with_record():
    votes = [vote(1, ["3.70"], [(1, "FOR")]), vote(2, ["3.70"], [(1, "FOR")], kind="amendment"),
             vote(3, ["3.70"], [(1, "FOR")])]
    rows = {r["key"]: r for r in cs.category_stats(votes, MEPS, {1, 2})["categories"]}
    key = next(k for k, r in rows.items() if r["votes"] == 3)
    assert rows[key]["final_trace"] == 1  # hlasování 2 je dílčí
    assert "final_trace" not in cs.category_stats(votes, MEPS)["categories"][0]  # bez podkladu pole chybí
