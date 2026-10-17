import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import quiz  # noqa: E402
from test_build_web import mep, vote  # noqa: E402


def law(vid, date, ref, positions, ptype="COD", kind="final", result="ADOPTED", topic="3.70.03"):
    v = vote(vid, date, positions)
    v.update(
        vote_kind=kind,
        result=result,
        title_cs=f"MOCK {ref}",
        procedure={"reference": ref, "type": ptype, "title": "MOCK"},
        topics={"oeil": [{"code": topic}]},
    )
    return v


def amendments(ref, n, start=1000):
    """n dílčích hlasování k proceduře (zvyšují počet jmenovitých hlasování)."""
    return [law(start + i, "2025-01-01", ref, [(1, "FOR")], kind="amendment") for i in range(n)]


MEPS = {i: mep(i) for i in range(1, 8)}
SPLIT = [(1, "FOR"), (2, "FOR"), (3, "FOR"), (4, "AGAINST"), (5, "AGAINST"), (6, "AGAINST")]  # 3 : 3, ne skoro jednomyslné


def test_rule_filters_and_orders_by_roll_calls():
    votes = [
        law(1, "2025-03-01", "2025/0001(COD)", SPLIT),
        law(2, "2025-04-01", "2025/0002(COD)", SPLIT),
        *amendments("2025/0002(COD)", 5),
        law(3, "2025-04-02", "2025/0003(COD)", [(1, "FOR"), (2, "FOR")]),  # Češi jednotní
        law(4, "2025-04-03", "2025/0004(INI)", SPLIT, ptype="INI"),  # není zákon
        law(5, "2024-09-01", "2024/0005(COD)", SPLIT),  # celé období: počítá se
    ]
    q = quiz.build_quiz(votes, MEPS)
    assert q["long"] == [2, 1, 5]  # nejvíc hlasování, pak novější
    assert {x["id"]: x["roll_calls"] for x in q["questions"]}[2] == 6


def test_newest_split_final_vote_per_procedure():
    votes = [law(1, "2025-03-01", "2025/0001(COD)", SPLIT), law(2, "2025-04-01", "2025/0001(COD)", [(1, "FOR"), (2, "FOR")])]
    assert quiz.build_quiz(votes, MEPS)["long"] == [1]  # novější je jednotné, bere se to rozdělené


def test_topic_cap_and_lopsided_half(monkeypatch):
    monkeypatch.setattr(quiz, "QUIZ_SHORT", 4)
    monkeypatch.setattr(quiz, "categories_for", lambda v: [v["topics"]["oeil"][0]["code"]])
    lop = [(1, "FOR"), (2, "FOR"), (3, "FOR"), (4, "AGAINST")]  # menšina 1 hlas
    votes = [law(i, f"2025-0{i}-01", f"2025/000{i}(COD)", lop, topic=f"{i}.10") for i in range(1, 5)]
    votes += [law(9, "2025-09-01", "2025/0009(COD)", SPLIT, topic="1.10")]
    q = quiz.build_quiz(votes, MEPS)
    lopsided_short = [i for i in q["short"] if i != 9]
    assert len(lopsided_short) == 2 and 9 in q["short"]  # nejvýš polovina skoro jednomyslných
    same_topic = [law(i, "2025-01-01", f"2025/01{i:02d}(COD)", SPLIT, topic="3.70.03") for i in range(5)]
    assert len(quiz.build_quiz(same_topic, MEPS)["long"]) == quiz.MAX_PER_TOPIC


def test_only_meps_in_mandate_have_positions():
    meps = {1: mep(1), 2: mep(2, end="2025-01-01")}
    assert quiz.build_quiz([law(1, "2025-03-01", "2025/0001(COD)", [(1, "FOR"), (2, "AGAINST")])], meps)["questions"] == []


def test_empty():
    q = quiz.build_quiz([], MEPS)
    assert q["questions"] == [] and q["short"] == [] and q["long"] == []
