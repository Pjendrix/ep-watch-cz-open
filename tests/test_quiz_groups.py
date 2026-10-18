"""Kvíz „Evropské frakce“ (scripts/quiz_groups.py): pravidlo výběru otázek a postoje frakcí. Data jen MOCK."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import quiz_groups as qg  # noqa: E402
from test_build_web import vote  # noqa: E402

# 4 frakce většinou pro, 4 většinou proti = frakce se rozešly
SPLIT_GROUPS = {
    "EPP": [100, 20, 5, 3], "SD": [90, 10, 0, 2], "RENEW": [50, 20, 3, 1], "GREEN_EFA": [40, 10, 2, 0],
    "PFE": [5, 70, 3, 4], "ECR": [10, 60, 4, 1], "ESN": [2, 20, 0, 3], "GUE_NGL": [1, 40, 4, 1], "NI": [10, 15, 2, 5],
}  # fmt: skip
TOPICS = {"env": "3.70.03", "def": "6.10", "soc": "4.10", "jus": "7.10", "ins": "8.40", "eco": "2.10", "dig": "3.30", "abr": "5.03",
          "tra": "3.20", "agr": "3.10", "civ": "1.10", "fin": "8.70"}  # fmt: skip


def _name(ref):
    """Název bez číslic (číslo procedury by regex na letopočty zkrátil a různé procedury by splynuly)."""
    return "".join(chr(97 + int(c)) if c.isdigit() else c for c in ref)


def mock(
    vid, date, ref, ptype="COD", kind="final", result="ADOPTED", topic="env", counts=(400, 250), groups=None, title=None, title_cs=None
):
    v = vote(vid, date, [])
    v.update(
        vote_kind=kind,
        result=result,
        title_cs=title_cs or f"MOCK zákon {_name(ref)}",
        procedure={"reference": ref, "type": ptype, "title": title or f"MOCK law {_name(ref)}"},
        topics={"oeil": [{"code": TOPICS[topic]}]},
        counts={"for": counts[0], "against": counts[1], "abstention": 10, "did_not_vote": 5},
        group_counts=groups or SPLIT_GROUPS,
    )
    return v


def extra(ref, n, start, ptype="COD"):
    """n dalších jmenovitých hlasování k proceduře (pozměňovací návrhy)."""
    return [mock(start + i, "2025-01-01", ref, ptype=ptype, kind="amendment") for i in range(n)]


def law(vid, ref, roll_calls=10, **kw):
    return [mock(vid, kw.pop("date", "2025-06-01"), ref, **kw), *extra(ref, roll_calls - 1, vid * 1000)]


def res(vid, ref, roll_calls=20, ptype="INI", **kw):
    return [mock(vid, kw.pop("date", "2025-06-01"), ref, ptype=ptype, **kw), *extra(ref, roll_calls - 1, vid * 1000, ptype)]


def ids(votes):
    return qg.build_quiz_groups(votes)["long"]


def test_group_position_majority_and_tie():
    assert qg.group_position([10, 5, 1, 7]) == {"pos": "F", "share": 0.625, "counts": [10, 5, 1, 7]}
    assert qg.group_position([2, 9, 1, 0])["pos"] == "A"
    assert qg.group_position([2, 3, 5, 0])["pos"] == "B"  # zdržení může být postoj
    assert qg.group_position([5, 5, 1, 0]) == {"pos": None, "share": None, "counts": [5, 5, 1, 0]}  # remíza: bez postoje
    assert qg.group_position([0, 0, 0, 9])["pos"] is None and qg.group_position(None)["pos"] is None  # nikdo nehlasoval


def test_only_final_adopted_or_rejected():
    votes = [
        *law(1, "2025/0001(COD)"),
        *law(2, "2025/0002(COD)", kind="amendment"),  # není závěrečné
        *law(3, "2025/0003(COD)", result="LAPSED"),
        *law(4, "2025/0004(COD)", result="REJECTED", topic="def"),
    ]
    assert ids(votes) == [1, 4]


def test_newest_qualifying_vote_per_procedure():
    """Z procedury nejnovější závěrečné hlasování, které pravidly projde (pozdější bez sporu se nebere)."""
    votes = [
        *law(1, "2025/0001(COD)", date="2025-03-01"),
        mock(2, "2025-09-01", "2025/0001(COD)", counts=(600, 50)),  # novější, ale menšina pod 20 %
        mock(3, "2025-02-01", "2025/0001(COD)"),  # starší a projde
    ]
    assert ids(votes) == [1]


def test_parliament_split_minimum():
    votes = [*law(1, "2025/0001(COD)", counts=(400, 100)), *law(2, "2025/0002(COD)", counts=(400, 99), topic="def")]  # 20 % / 19,8 %
    assert ids(votes) == [1]


def test_groups_must_split():
    two_against = {**{g: [90, 5, 0, 0] for g in qg.GROUPS}, "PFE": [5, 70, 0, 0], "ESN": [1, 20, 0, 0]}
    one_against = {**{g: [90, 5, 0, 0] for g in qg.GROUPS}, "PFE": [5, 70, 0, 0], "ESN": [10, 10, 0, 0]}  # ESN remíza
    ni_only = {**{g: [90, 5, 0, 0] for g in qg.GROUPS}, "PFE": [5, 70, 0, 0], "NI": [0, 50, 0, 0]}  # NI se nepočítá
    votes = [
        *law(1, "2025/0001(COD)", groups=two_against),
        *law(2, "2025/0002(COD)", groups=one_against, topic="def"),
        *law(3, "2025/0003(COD)", groups=ni_only, topic="soc"),
    ]
    assert ids(votes) == [1]


def test_law_two_paths():
    """Zákon projde s aspoň 10 jmenovitými hlasováními, nebo jako dohoda s Radou s menšinou aspoň 30 %."""
    votes = [
        *law(1, "2025/0001(COD)", roll_calls=10),
        *law(2, "2025/0002(COD)", roll_calls=9, topic="def"),  # málo hlasování, není dohoda
        *law(3, "2025/0003(COD)", roll_calls=2, kind="provisional_agreement", counts=(350, 150), topic="soc"),  # 30 %
        *law(4, "2025/0004(COD)", roll_calls=2, kind="provisional_agreement", counts=(400, 150), topic="jus"),  # 27 %
        *law(5, "2025/0005(CNS)", roll_calls=12, topic="ins"),
        *law(6, "2025/0006(NLE)", roll_calls=12, ptype="NLE", topic="eco"),  # NLE není zákon (a na usnesení má málo hlasování)
    ]
    q = qg.build_quiz_groups(votes)
    assert q["long"] == [5, 1, 3]
    assert {x["id"]: x["kind"] for x in q["questions"]} == {5: "zakon", 1: "zakon", 3: "zakon"}


def test_resolution_thresholds():
    votes = [
        *res(1, "2025/2001(INI)", roll_calls=20, counts=(350, 150)),
        *res(2, "2025/2002(INI)", roll_calls=19, counts=(350, 150), topic="def"),  # málo hlasování
        *res(3, "2025/2003(RSP)", roll_calls=30, counts=(400, 150), ptype="RSP", topic="soc"),  # menšina 27 %
    ]
    assert ids(votes) == [1]


def test_order_laws_first_then_resolutions_by_roll_calls_then_newer():
    votes = [
        *res(1, "2025/2001(INI)", roll_calls=50, topic="soc"),
        *law(2, "2025/0002(COD)", roll_calls=12, topic="def", date="2025-01-01"),
        *law(3, "2025/0003(COD)", roll_calls=12, topic="jus", date="2025-05-01"),
        *law(4, "2025/0004(COD)", roll_calls=20, topic="ins"),
    ]
    assert ids(votes) == [4, 3, 2, 1]


def test_max_per_topic_across_whole_test():
    votes = [v for i in range(1, 5) for v in law(i, f"2025/000{i}(COD)", roll_calls=20 - i)]  # 4 zákony env
    votes += res(9, "2025/2009(INI)", topic="env") + res(8, "2025/2008(INI)", topic="def")
    assert ids(votes) == [1, 2, 3, 8]  # 4. zákon ani usnesení env se nevejdou


def test_recurring_reports_keep_newest():
    votes = [
        *res(1, "2024/0176(BUD)", ptype="BUD", roll_calls=100, date="2024-11-27", topic="soc",
             title="2025 general budget: all sections", title_cs="Souhrnný rozpočet Evropské unie na rozpočtový rok 2025 – všechny oddíly"),
        *res(2, "2025/0210(BUD)", ptype="BUD", roll_calls=30, date="2025-11-26", topic="soc",
             title="General budget of the European Union for the financial year 2026 - all sections",
             title_cs="Souhrnný rozpočet Evropské unie na rozpočtový rok 2026 – všechny oddíly"),
        *res(3, "2024/2078(INI)", roll_calls=40, date="2025-06-18", topic="ins",
             title="The Commission’s 2024 Rule of Law report", title_cs="Zpráva Komise o právním státu 2024"),
        *res(4, "2025/2239(INI)", roll_calls=25, date="2026-04-29", topic="ins",
             title="The Commission’s 2025 Rule of Law report", title_cs="Zpráva Komise o právním státu v roce 2025"),
        *res(5, "2024/2019(DEC)", ptype="DEC", roll_calls=60, date="2025-05-07", topic="def",
             title="2023 discharge: Commission", title_cs="Udělení absolutoria za rok 2023: souhrnný rozpočet EU - Komise"),
        *res(6, "2025/2145(DEC)", ptype="DEC", roll_calls=25, date="2026-04-29", topic="def",
             title="Discharge 2024: Commission", title_cs="Udělení absolutoria za rok 2024: souhrnný rozpočet EU – Komise"),
    ]  # fmt: skip
    assert sorted(ids(votes)) == [2, 4, 6]  # shoda českého nebo anglického názvu bez letopočtu, pomlčky sjednocené


def _many(n_laws, n_res):
    topics = list(TOPICS)
    votes = []
    for i in range(n_laws):
        votes += law(100 + i, f"2025/{i:04}(COD)", roll_calls=60 - i, topic=topics[i % len(topics)])
    for i in range(n_res):
        votes += res(300 + i, f"2025/{2000 + i}(INI)", roll_calls=60 - i, topic=topics[i % len(topics)])
    return votes


def test_lengths_and_short_subset_of_long():
    q = qg.build_quiz_groups(_many(30, 30))
    kinds = {x["id"]: x["kind"] for x in q["questions"]}
    assert len(q["long"]) == qg.LONG and sum(kinds[i] == "zakon" for i in q["long"]) == qg.LONG_LAWS
    assert len(q["short"]) == qg.SHORT and sum(kinds[i] == "zakon" for i in q["short"]) == qg.SHORT_LAWS
    assert set(q["short"]) <= set(q["long"])
    assert q["short"] == [i for i in q["long"] if i in q["short"]]  # stejné pořadí
    assert len(q["questions"]) == len(q["long"])


def test_few_laws_filled_with_resolutions():
    q = qg.build_quiz_groups(_many(4, 30))
    kinds = {x["id"]: x["kind"] for x in q["questions"]}
    assert len(q["long"]) == qg.LONG and sum(kinds[i] == "zakon" for i in q["long"]) == 4
    assert len(q["short"]) == qg.SHORT and sum(kinds[i] == "zakon" for i in q["short"]) == 4


def test_not_enough_candidates_gives_shorter_test():
    q = qg.build_quiz_groups(_many(3, 4))
    assert len(q["long"]) == 7 and len(q["short"]) == 7  # prahy se nevolní


def test_question_fields_and_groups():
    q = qg.build_quiz_groups(law(1, "2025/0001(COD)", roll_calls=12))
    x = q["questions"][0]
    assert {"id", "date", "title", "title_en", "description", "procedure", "proc_type", "kind", "vote_kind", "result", "topic",
            "roll_calls", "counts", "groups"} <= set(x)  # fmt: skip
    assert x["proc_type"] == "COD" and x["roll_calls"] == 12 and x["counts"] == [400, 250, 10] and x["topic"] == "env"
    assert list(x["groups"])[:8] == qg.GROUPS and x["groups"]["NI"]["pos"] == "A"  # NI jen informativně
    assert x["groups"]["EPP"] == {"pos": "F", "share": round(100 / 125, 4), "counts": [100, 20, 5, 3]}
    assert q["params"]["MIN_MINORITY"] == qg.MIN_MINORITY and q["rule"]


def test_missing_group_counts_is_error():
    v = mock(1, "2025-01-01", "2025/0001(COD)")
    del v["group_counts"]
    with pytest.raises(Exception, match="group_counts"):
        qg.build_quiz_groups([v])
