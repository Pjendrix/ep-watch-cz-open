import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import compute_stats as cs  # noqa: E402
import ep_groups as eg  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"

# MOCK poslanec 1: EP NI do 20. 10., PfE od 21. 10.; HowTheyVote ho vede pořád jako NI (jako Konečnou v exportu 2026-10-24).
# MOCK poslanec 2: oba zdroje se shodují (EPP), slouží k mapě kódů EP → HowTheyVote.
MEPS = [
    {
        "id": 1,
        "mandates": [{"start": "2024-07-16", "end": None}],
        "groups": [{"code": "NI", "start": "2024-07-16", "end": "2026-10-20"}, {"code": "PFE", "start": "2026-10-21", "end": None}],
    },
    {"id": 2, "mandates": [{"start": "2024-07-16", "end": None}], "groups": [{"code": "PPE", "start": "2024-07-16", "end": None}]},
    {"id": 3, "mandates": [{"start": "2024-07-16", "end": None}], "groups": [{"code": "PFE", "start": "2024-07-16", "end": None}]},
]


def vote(i, date, pos1, groups1="NI"):
    return {
        "id": i,
        "date": date,
        "result": "ADOPTED",
        "is_main": True,
        "counts": {"for": 3, "against": 3, "abstention": 0, "did_not_vote": 0},
        # PfE 2:2 bez poslance 1 (ten je u HowTheyVote v NI) → většina PfE rozhodne až přesun poslance 1
        "group_counts": {"NI": [1 if pos1 == "FOR" else 0, 1 if pos1 == "AGAINST" else 0, 0, 0], "PFE": [2, 2, 0, 0], "EPP": [0, 1, 0, 0]},
        "cz_positions": [
            {"member_id": 1, "position": pos1, "group_code": groups1},
            {"member_id": 2, "position": "AGAINST", "group_code": "EPP"},
            {"member_id": 3, "position": "FOR", "group_code": "PFE"},
        ],
    }


def votes():
    return [vote(1, "2026-10-20", "FOR"), vote(2, "2026-10-21", "FOR"), vote(3, "2026-10-22", "AGAINST")]


def test_apply_uses_ep_membership_and_keeps_htv_value():
    vs = votes()
    eg.apply(vs, MEPS)
    p = {v["id"]: v["cz_positions"][0] for v in vs}
    assert p[1]["group_code"] == "NI" and "group_code_htv" not in p[1]  # do 20. 10. NI v obou zdrojích
    assert p[2]["group_code"] == "PFE" and p[2]["group_code_htv"] == "NI"
    assert vs[0]["cz_positions"][1]["group_code"] == "EPP"  # kód EP PPE → kód HowTheyVote EPP


def test_apply_is_idempotent():
    vs = votes()
    eg.apply(vs, MEPS)
    once = json.dumps(vs, sort_keys=True)
    eg.apply(vs, MEPS)
    assert json.dumps(vs, sort_keys=True) == once


def test_without_ep_group_keeps_htv():
    vs = [vote(1, "2026-10-21", "FOR")]
    meps = [dict(MEPS[0], groups=[]), MEPS[1], MEPS[2]]
    eg.apply(vs, meps)
    assert vs[0]["cz_positions"][0]["group_code"] == "NI" and "group_code_htv" not in vs[0]["cz_positions"][0]


def test_conflicts_report_period_and_count():
    vs = votes()
    eg.apply(vs, MEPS)
    assert eg.conflicts(vs) == [{"member_id": 1, "from": "2026-10-21", "to": "2026-10-22", "htv": "NI", "ep": "PFE", "votes": 2}]


def test_majority_counts_move_vote_only_for_majority():
    vs = votes()
    eg.apply(vs, MEPS)
    v = vs[1]
    gc = eg.majority_counts(v)
    assert gc["NI"] == [0, 0, 0, 0] and gc["PFE"] == [3, 2, 0, 0]
    assert v["group_counts"]["PFE"] == [2, 2, 0, 0]  # zobrazené počty zůstávají podle HowTheyVote
    assert eg.majority_counts(vs[0]) is vs[0]["group_counts"]  # bez rozporu beze změny


def test_loyalty_counts_only_votes_in_group():
    vs = votes()
    eg.apply(vs, MEPS)
    stats = cs.compute(MEPS, vs, [])
    loyal = stats["1"]["total"]["group_loyalty"] if "1" in stats else stats[1]["total"]["group_loyalty"]
    # 20. 10. NI (nepočítá se); 21. 10. PRO = většina PfE 3:2; 22. 10. PROTI → PfE 2:3 → PROTI = většina
    assert loyal == [2, 2]


def test_short_group_threshold():
    assert eg.short_group(MEPS[0], [143, 218]) == {"since": "2026-10-21", "votes": 218}
    assert eg.short_group(MEPS[0], [400, eg.SHORT_GROUP_VOTES]) is None
    assert eg.short_group(MEPS[0], [0, 0]) is None


def test_real_data_konecna_loyalty_only_from_pfe():
    stats_path = DATA / "stats.json"
    if not stats_path.exists():
        pytest.skip("bez dat (export do veřejného repa)")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    loyal = stats["meps"]["23699"]["total"]["group_loyalty"]
    conflicts = stats["sources"]["group_conflicts"]
    kon = [c for c in conflicts if c["member_id"] == 23699]
    if not kon:
        pytest.skip("HowTheyVote už rozpor opravil")
    assert loyal[1] > 0 and kon[0]["from"] == "2026-10-21" and loyal[1] <= kon[0]["votes"]
