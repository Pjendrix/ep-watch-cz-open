import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import duel  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
MEPS = {
    1: {"id": 1, "mandates": [{"start": "2024-07-16", "end": None}]},
    2: {"id": 2, "mandates": [{"start": "2024-07-16", "end": None}]},
    3: {"id": 3, "mandates": [{"start": "2024-07-16", "end": "2025-01-31"}]},
}


def vote(i, date, positions, topics=("6.10",)):
    return {
        "id": i,
        "date": date,
        "topics": {"oeil": [{"code": t + ".01"} for t in topics]},
        "cz_positions": [{"member_id": m, "position": p, "group_code": f"MOCK_G{m}"} for m, p in positions.items()],
    }


def test_pair_key_is_canonical():
    assert duel.pair_key(256851, 23699) == duel.pair_key(23699, 256851) == "23699-256851"


def test_diverged_only_for_against_in_mandate_newest_first():
    votes = [
        vote(10, "2025-01-10", {1: "FOR", 2: "AGAINST", 3: "AGAINST"}),
        vote(11, "2025-03-01", {1: "FOR", 2: "ABSTENTION", 3: "AGAINST"}),  # 3 už není v mandátu, zdržení se nepočítá
        vote(12, "2025-04-01", {1: "AGAINST", 2: "FOR", 3: "FOR"}),
    ]
    d = duel.diverged(votes, MEPS)
    assert d["1-2"] == [[12, "AGAINST", "FOR", "MOCK_G1", "MOCK_G2"], [10, "FOR", "AGAINST", "MOCK_G1", "MOCK_G2"]]
    assert [r[0] for r in d["1-3"]] == [10]
    assert "2-3" not in d


def test_pair_topics_counts_both_voted_including_abstention():
    votes = [
        vote(1, "2025-01-10", {1: "FOR", 2: "FOR"}),
        vote(2, "2025-01-11", {1: "ABSTENTION", 2: "FOR"}),
        vote(3, "2025-01-12", {1: "FOR", 2: "DID_NOT_VOTE"}),
        vote(4, "2025-01-13", {1: "FOR", 2: "FOR"}, topics=("8.70",)),
    ]
    t = duel.pair_topics(votes, MEPS, ["6.10"])
    assert t["1-2"] == {"6.10": [1, 2]}


def test_mep_metrics_null_when_source_missing_and_for_non_attached():
    prof = {
        "total": {
            "attendance": [8, 10],
            "group_loyalty": [0, 0],
            "positions": {"FOR": 5, "AGAINST": 3, "ABSTENTION": 0, "DID_NOT_VOTE": 2},
        },
        "against_group": {"count": 0},
        "decisive": [{"id": 1}],
        "own_work": None,
        "activity": None,
        "amendments": None,
    }
    m = duel.mep_metrics(prof)
    assert m["against_group"] is None and m["reports"] is None and m["speeches"] is None and m["amendments"] is None
    assert m["votes_in_mandate"] == 10 and m["decisive"] == 1


@pytest.fixture(scope="module")
def real():
    if not (DATA / "duel.json").exists():
        pytest.skip("bez dat duelu (export do veřejného repa)")
    return json.loads((DATA / "duel.json").read_text(encoding="utf-8")), json.loads((DATA / "stats.json").read_text(encoding="utf-8"))


def test_repo_duel_metrics_match_profiles(real):
    """Duel ukazuje stejná čísla jako p/{id}.html: metriky jsou z profilu data/meps/{id}.json."""
    d, _ = real
    for m in d["meps"]:
        prof = json.loads((DATA / "meps" / f"{m['id']}.json").read_text(encoding="utf-8"))
        assert m["metrics"] == duel.mep_metrics(prof), m["id"]


def test_repo_agreement_is_symmetric(real):
    d, stats = real
    for k, p in d["pairs"].items():
        a, b = k.split("-")
        assert stats["meps"][a]["pairwise"].get(b, [0, 0]) == stats["meps"][b]["pairwise"].get(a, [0, 0]) == p["agreement"], k
        assert int(a) < int(b)


def test_repo_diverged_only_for_against(real):
    d, _ = real
    for k, p in d["pairs"].items():
        assert len(p["diverged_key"]) <= duel.DIVERGED_KEY
        assert len(p["diverged_key"]) <= p["diverged_all"]
        for row in p["diverged_key"]:
            assert {row[1], row[2]} == {"FOR", "AGAINST"}, (k, row)
            assert str(row[0]) in d["votes"]


def test_pair_shards_compact_rows():
    votes = [vote(10, "2025-01-10", {1: "FOR", 2: "AGAINST"})]
    assert duel.pair_shards(votes, list(MEPS.values())) == {
        "1-2": {"pair": "1-2", "fields": ["id", "a", "b", "ga", "gb"], "rows": [[10, "FOR", "AGAINST", "MOCK_G1", "MOCK_G2"]]}
    }
