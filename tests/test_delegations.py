import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import delegations as dg  # noqa: E402


# MOCK data: počty hlasů po státech [pro, proti, zdržel se, nehlasoval]
def vote(i, n_for, n_against, result, final=False, date="2025-01-01"):
    return {"id": i, "date": date, "result": result, "is_final": final, "counts": {"for": n_for, "against": n_against}}


CC = {
    1: {"CZE": [3, 0, 0, 0], "AAA": [2, 1, 0, 0], "BBB": [0, 3, 0, 0]},  # CZE jednotně, AAA rozdělená
    2: {"CZE": [1, 1, 0, 1], "AAA": [3, 0, 0, 0], "BBB": [1, 0, 0, 2]},  # BBB: jen jeden hlasující (nepočítá se)
    3: {"CZE": [3, 0, 0, 0], "AAA": [0, 0, 3, 0], "BBB": [0, 3, 0, 0]},  # zdržení: AAA se neposuzuje
    9: {"CZE": [3, 0, 0, 0], "AAA": [3, 0, 0, 0], "BBB": [3, 0, 0, 0], "XXX": [3, 0, 0, 0]},  # poslední hlasování: velikosti
}
VOTES = [
    vote(1, 11, 10, "ADOPTED", final=True),  # těsné; bez CZE (3 pro) by 8 : 10 -> zamítnuto = rozhodli
    vote(2, 40, 10, "ADOPTED"),  # není těsné
    vote(3, 30, 25, "ADOPTED"),  # těsné (5), bez BBB (0 pro, 3 proti) 30 : 22 stále přijato
    vote(9, 9, 0, "ADOPTED", date="2025-02-01"),
]


def test_unity_counts_only_votes_with_two_deciding_members():
    cze = dg.delegation_metrics(CC, VOTES, "CZE")
    assert cze["unity"] == [3, 4] and cze["unity_final"] == [1, 1]  # hlasování 2 má 1 pro a 1 proti = rozdělená
    assert dg.delegation_metrics(CC, VOTES, "AAA")["unity"] == [2, 3]  # hlasování 3: jen zdržení, neposuzuje se
    assert dg.delegation_metrics(CC, VOTES, "BBB")["unity"] == [3, 3]  # hlasování 2: jediný hlasující, neposuzuje se


def test_decisive_counts_same_rule_as_czech():
    cze = dg.delegation_metrics(CC, VOTES, "CZE")
    assert cze["decisive"] == {"all": 1, "final": 1}  # hlasování 1: 8 : 10; u 3 a 9 by přijato zůstalo
    assert cze["close"] == {"all": 3, "final": 1}  # 1, 3 a 9; hlasování 2 (40 : 10) není těsné
    assert dg.delegation_metrics(CC, VOTES, "BBB")["decisive"] == {"all": 0, "final": 0}
    # remíza po odečtení hlasů není „přijato“ (stejné pravidlo jako compute_stats.simple_result)
    assert dg.delegation_metrics(CC, VOTES, "AAA")["decisive"] == {"all": 1, "final": 1}


def test_peers_by_seats_and_ranges():
    d = dg.compute_delegations(CC, VOTES, own="CZE", min_seats=3, max_seats=3)
    assert d["peers"] == ["AAA", "BBB", "XXX"] and set(d["countries"]) == {"CZE", "AAA", "BBB", "XXX"}
    assert d["peer_range"]["decisive"] == {"min": 0, "max": 1}
    assert d["peer_range"]["unity"]["max"] == 1.0  # XXX: jediné hlasování, jednotně
    d2 = dg.compute_delegations(CC, VOTES, own="CZE", min_seats=4, max_seats=5)
    assert d2["peers"] == [] and d2["peer_range"]["unity"] == {"min": None, "max": None}
