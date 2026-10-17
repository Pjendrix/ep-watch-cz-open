import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import quiz  # noqa: E402
from test_build_web import mep, vote  # noqa: E402


def law(vid, date, ref, positions, ptype="COD", kind="final", result="ADOPTED"):
    v = vote(vid, date, positions)
    v.update(vote_kind=kind, result=result, title_cs=f"MOCK {ref}", procedure={"reference": ref, "type": ptype, "title": "MOCK"})
    return v


MEPS = {m["id"]: m for m in (mep(1), mep(2), mep(3), mep(4))}


def test_rule_picks_split_final_laws_one_per_procedure():
    votes = [
        law(1, "2025-03-01", "2025/0001(COD)", [(1, "FOR"), (2, "AGAINST")]),
        law(2, "2025-04-01", "2025/0001(COD)", [(1, "FOR"), (2, "AGAINST"), (3, "FOR")]),   # novější ze stejné procedury
        law(3, "2025-04-02", "2025/0002(COD)", [(1, "FOR"), (2, "FOR")]),                   # Češi nerozdělení
        law(4, "2025-04-03", "2025/0003(INI)", [(1, "FOR"), (2, "AGAINST")], ptype="INI"),  # není zákon
        law(5, "2025-04-04", "2025/0004(COD)", [(1, "FOR"), (2, "AGAINST")], kind="amendment"),  # není závěrečné
        law(6, "2024-01-01", "2023/0005(COD)", [(1, "FOR"), (2, "AGAINST")]),               # starší než 12 měsíců
    ]
    q = quiz.build_quiz(votes, MEPS)
    assert [x["id"] for x in q["questions"]] == [2]
    assert q["questions"][0]["positions"] == {"1": "F", "2": "A", "3": "F"}
    assert q["to"] == "2025-04-04" and q["rule"] == quiz.QUIZ_RULE


def test_most_split_first_and_size_limit(monkeypatch):
    monkeypatch.setattr(quiz, "QUIZ_SIZE", 2)
    votes = [
        law(1, "2025-03-01", "2025/0001(COD)", [(1, "FOR"), (2, "FOR"), (3, "FOR"), (4, "AGAINST")]),        # 1:3
        law(2, "2025-03-02", "2025/0002(COD)", [(1, "FOR"), (2, "AGAINST")]),                               # 1:1
        law(3, "2025-03-03", "2025/0003(COD)", [(1, "FOR"), (2, "FOR"), (3, "AGAINST"), (4, "AGAINST")]),   # 2:2
    ]
    q = quiz.build_quiz(votes, MEPS)
    assert [x["id"] for x in q["questions"]] == [3, 2]  # dvě nejrozdělenější, zobrazené od nejnovějšího


def test_only_meps_in_mandate_have_positions():
    meps = {1: mep(1), 2: mep(2, end="2025-01-01")}
    q = quiz.build_quiz([law(1, "2025-03-01", "2025/0001(COD)", [(1, "FOR"), (2, "AGAINST")])], meps)
    assert q["questions"] == []  # bez poslance 2 už Češi rozdělení nejsou


def test_empty():
    assert quiz.build_quiz([], MEPS)["questions"] == []
