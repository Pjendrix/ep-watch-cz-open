import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import compute_stats as cs  # noqa: E402


def mep(i, start="2024-07-16", end=None, groups=(), parties=()):
    return {"id": i, "mandates": [{"start": start, "end": end}], "groups": list(groups), "parties": list(parties)}


def pos(i, position, group="EPP"):
    return {"member_id": i, "position": position, "group_code": group}


def vote(vid, date, positions, group_counts=None, is_main=False, result=None, counts=(0, 0), topics=()):
    return {
        "id": vid,
        "date": date,
        "is_main": is_main,
        "group_counts": group_counts or {},
        "cz_positions": positions,
        "result": result,
        "counts": {"for": counts[0], "against": counts[1], "abstention": 0, "did_not_vote": 0},
        "topics": {"oeil": [{"code": t, "label": f"MOCK {t}"} for t in topics]},
    }


@pytest.mark.parametrize(
    "counts,expected",
    [
        ({"FOR": 3, "AGAINST": 1}, "FOR"),
        ({"FOR": 1, "AGAINST": 1}, None),  # remíza
        ({"ABSTENTION": 2, "FOR": 1}, "ABSTENTION"),
        ({"DID_NOT_VOTE": 9}, None),  # nehlasující se nepočítají
        ({}, None),
    ],
)
def test_majority(counts, expected):
    assert cs.majority(counts) == expected


def test_group_majority_ignores_absent_and_ni():
    gc = {"EPP": [10, 2, 0, 50], "NI": [5, 0, 0, 0]}
    assert cs.group_majority(gc, "EPP") == "FOR"
    assert cs.group_majority(gc, "NI") is None
    assert cs.group_majority(gc, None) is None
    assert cs.group_majority(gc, "SD") is None


def test_attendance_only_within_mandate():
    meps = [mep(1, end="2024-09-30"), mep(2)]
    votes = [
        vote(1, "2024-09-16", [pos(1, "FOR"), pos(2, "DID_NOT_VOTE")], is_main=True),
        vote(2, "2024-10-07", [pos(1, "DID_NOT_VOTE"), pos(2, "FOR")]),  # 1 už není v mandátu
    ]
    s = cs.compute(meps, votes)
    assert s["1"]["total"]["attendance"] == [1, 1]
    assert s["1"]["total"]["attendance_main"] == [1, 1]
    assert s["2"]["total"]["attendance"] == [1, 2]
    assert s["2"]["total"]["attendance_main"] == [0, 1]
    assert s["2"]["total"]["positions"] == {"FOR": 1, "AGAINST": 0, "ABSTENTION": 0, "DID_NOT_VOTE": 1}
    assert list(s["2"]["monthly"]) == ["2024-09", "2024-10"]
    assert s["2"]["monthly"]["2024-10"]["attendance"] == [1, 1]


def test_group_loyalty_uses_group_at_vote_date():
    meps = [mep(1)]
    gc = {"EPP": [100, 5, 0, 0], "PFE": [3, 50, 1, 0]}
    votes = [
        vote(1, "2024-09-16", [pos(1, "FOR", "EPP")], gc),  # loajální k EPP
        vote(2, "2024-10-16", [pos(1, "FOR", "PFE")], gc),  # po přestupu proti většině PfE
        vote(3, "2024-11-16", [pos(1, "AGAINST", "NI")], gc),  # nezařazený: nepočítá se
        vote(4, "2024-11-17", [pos(1, "DID_NOT_VOTE", "EPP")], gc),  # nehlasoval: nepočítá se
    ]
    assert cs.compute(meps, votes)["1"]["total"]["group_loyalty"] == [1, 2]


def test_cz_agreement_excludes_self_and_ties():
    meps = [mep(1), mep(2), mep(3), mep(4)]
    votes = [
        # ostatní pro 1: FOR, FOR, AGAINST -> většina FOR, 1 souhlasí
        vote(1, "2024-09-16", [pos(1, "FOR"), pos(2, "FOR"), pos(3, "FOR"), pos(4, "AGAINST")]),
        # ostatní pro 1: FOR, AGAINST, nehlasoval -> remíza, nepočítá se
        vote(2, "2024-09-17", [pos(1, "FOR"), pos(2, "FOR"), pos(3, "AGAINST"), pos(4, "DID_NOT_VOTE")]),
    ]
    s = cs.compute(meps, votes)
    assert s["1"]["total"]["cz_agreement"] == [1, 1]
    assert s["4"]["total"]["cz_agreement"] == [0, 1]
    assert s["4"]["total"]["attendance"] == [1, 2]


def test_pairwise_only_when_both_voted():
    meps = [mep(1), mep(2)]
    votes = [
        vote(1, "2024-09-16", [pos(1, "FOR"), pos(2, "FOR")]),
        vote(2, "2024-09-17", [pos(1, "FOR"), pos(2, "AGAINST")]),
        vote(3, "2024-09-18", [pos(1, "FOR"), pos(2, "DID_NOT_VOTE")]),
    ]
    s = cs.compute(meps, votes)
    assert s["1"]["pairwise"] == {"2": [1, 2]}
    assert s["2"]["pairwise"] == {"1": [1, 2]}


def test_unknown_mep_raises():
    with pytest.raises(cs.FormatError, match="nejsou v meps.json"):
        cs.compute([mep(1)], [vote(1, "2024-09-16", [pos(99, "FOR")])])


def test_missing_vote_field_raises():
    v = vote(1, "2024-09-16", [pos(1, "FOR")])
    del v["group_counts"]
    with pytest.raises(cs.FormatError, match="group_counts"):
        cs.compute([mep(1)], [v])


def test_derive_group_codes_from_both_sources():
    g = lambda code, s, e=None: {"code": code, "start": s, "end": e, "name_cs": f"MOCK {code}"}
    meps = [mep(1, groups=[g("PPE", "2024-07-16")]), mep(2, groups=[g("PFE", "2024-07-16", "2024-12-31"), g("NI", "2025-01-01")])]
    votes = [vote(1, "2024-09-16", [pos(1, "FOR", "EPP"), pos(2, "FOR", "PFE")]), vote(2, "2025-02-01", [pos(2, "FOR", "NI")])]
    assert cs.derive_group_codes(meps, votes) == {"EPP": "PPE", "PFE": "PFE", "NI": "NI"}


def test_run_writes_files(tmp_path):
    data = tmp_path / "data"
    (data / "votes").mkdir(parents=True)
    party = {"org_id": "20", "short_label": "MOCK_P", "name": "MOCK strana", "start": "2024-07-16", "end": None}
    meps = {
        "source": {"name": "MOCK"},
        "meps": [{**mep(1, groups=[{"code": "PPE", "start": "2024-07-16", "end": None, "name_cs": "MOCK lidovci"}], parties=[party])}],
    }
    (data / "meps.json").write_text(json.dumps(meps), encoding="utf-8")
    index = {
        "source": {"release": "MOCK"},
        "months": [{"month": "2024-09", "votes": 1}],
        "groups": [{"code": "EPP", "label": "MOCK EPP", "short_label": "EPP"}],
    }
    (data / "votes" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    month = {"votes": [vote(1, "2024-09-16", [pos(1, "FOR")], {"EPP": [5, 1, 0, 0]}, True)]}
    (data / "votes" / "2024-09.json").write_text(json.dumps(month), encoding="utf-8")
    assets = tmp_path / "assets"
    (assets / "logos" / "cz").mkdir(parents=True)
    (assets / "logos" / "cz" / "20.svg").write_text("<svg/>")

    stats = cs.run(data, assets)
    assert stats["meps"]["1"]["total"]["group_loyalty"] == [1, 1]
    assert stats["period"] == {"from": "2024-09-16", "to": "2024-09-16"}
    groups = json.loads((data / "groups.json").read_text(encoding="utf-8"))
    assert groups == [
        {
            "code": "EPP",
            "ep_code": "PPE",
            "short_label": "EPP",
            "label": "MOCK EPP",
            "name_cs": "MOCK lidovci",
            "color": None,
            "logo": None,
            "brand_color": None,
            "chart_color": None,
            "logo_source": None,
            "logo_aspect": None,
        }
    ]
    parties = json.loads((data / "parties.json").read_text(encoding="utf-8"))
    assert parties == [
        {
            "id": 20,
            "short_label": "MOCK_P",
            "name": "MOCK strana",
            "independent": False,
            "color": None,
            "logo": "assets/logos/cz/20.svg",
            "brand_color": None,
            "chart_color": None,
            "logo_source": None,
            "logo_aspect": None,
        }
    ]


def test_manual_colors_are_merged_and_never_written(tmp_path):
    manual_path = tmp_path / "colors.json"
    manual_path.write_text(
        json.dumps(
            {
                "_poznamka": "MOCK",
                "groups": {"EPP": {"color": "#123abc", "logo": None}},
                "parties": {"20": {"color": None, "logo": "assets/MOCK.svg"}},
            }
        ),
        encoding="utf-8",
    )
    before = manual_path.read_text(encoding="utf-8")
    manual = cs.load_manual(manual_path)
    groups = cs.build_groups([{"code": "EPP", "label": "MOCK", "short_label": "EPP"}], [], [], tmp_path, manual)
    assert groups[0]["color"] == "#123abc"
    party = {"org_id": "20", "short_label": "MOCK_P", "name": "MOCK", "start": "2024-07-16", "end": None}
    parties = cs.build_parties([mep(1, parties=[party])], tmp_path, manual)
    assert parties[0]["color"] is None and parties[0]["logo"] == "assets/MOCK.svg"
    assert manual_path.read_text(encoding="utf-8") == before


def test_manual_missing_file_is_empty(tmp_path):
    assert cs.load_manual(tmp_path / "nic.json") == {"groups": {}, "parties": {}}


def test_brand_color_wins_and_needs_source(tmp_path):
    path = tmp_path / "colors.json"
    path.write_text(
        json.dumps({"groups": {"EPP": {"brand_color": "#004494", "brand_source": "MOCK_URL", "chart_color": "#3B82F6"}}, "parties": {}}),
        encoding="utf-8",
    )
    g = cs.build_groups([{"code": "EPP", "label": "MOCK", "short_label": "EPP"}], [], [], tmp_path, cs.load_manual(path))[0]
    assert (g["color"], g["brand_color"], g["chart_color"]) == ("#004494", "#004494", "#3B82F6")
    path.write_text(json.dumps({"groups": {"EPP": {"brand_color": "#004494"}}, "parties": {}}), encoding="utf-8")
    with pytest.raises(cs.FormatError, match="brand_source"):
        cs.load_manual(path)


def test_logos_manifest(tmp_path):
    public = tmp_path / "public"
    (public / "assets" / "logos" / "ep").mkdir(parents=True)
    (public / "assets" / "logos" / "ep" / "ECR.svg").write_text("<svg/>", encoding="utf-8")
    path = tmp_path / "logos.json"
    path.write_text(
        json.dumps(
            {
                "groups": {"ECR": {"file": "assets/logos/ep/ECR.svg", "source": "MOCK_URL"}, "EPP": {"file": None, "source": "MOCK"}},
                "parties": {},
            }
        ),
        encoding="utf-8",
    )
    logos = cs.load_logos(path, public)
    assert logos["groups"] == {"ECR": {"logo": "assets/logos/ep/ECR.svg", "logo_source": "MOCK_URL"}}
    g = cs.build_groups([{"code": "ECR", "label": "MOCK", "short_label": "ECR"}], [], [], public / "assets", None, logos)[0]
    assert g["logo"] == "assets/logos/ep/ECR.svg" and g["logo_source"] == "MOCK_URL"
    path.write_text(json.dumps({"groups": {"ECR": {"file": "assets/logos/ep/ECR.svg", "source": None}}, "parties": {}}), encoding="utf-8")
    with pytest.raises(cs.FormatError, match="bez zdroje"):
        cs.load_logos(path, public)
    path.write_text(json.dumps({"groups": {"ECR": {"file": "assets/chybi.svg", "source": "x"}}, "parties": {}}), encoding="utf-8")
    with pytest.raises(cs.FormatError, match="neexistuje"):
        cs.load_logos(path, public)


@pytest.mark.parametrize("color", ["red", "#12345", "#GGGGGG"])
def test_manual_invalid_color_raises(tmp_path, color):
    path = tmp_path / "colors.json"
    path.write_text(json.dumps({"groups": {"EPP": {"color": color}}, "parties": {}}), encoding="utf-8")
    with pytest.raises(cs.FormatError, match="#RRGGBB"):
        cs.load_manual(path)


# --- fáze C ---------------------------------------------------------------


def test_outcome_agreement_counts_only_for_against_and_decided():
    meps = [mep(1)]
    gc = {"EPP": [100, 50, 0, 0]}
    votes = [
        vote(1, "2024-09-16", [pos(1, "FOR")], gc, is_main=True, result="ADOPTED", counts=(300, 200)),
        vote(2, "2024-09-17", [pos(1, "FOR")], gc, result="REJECTED", counts=(200, 300)),
        vote(3, "2024-09-18", [pos(1, "ABSTENTION")], gc, result="ADOPTED", counts=(300, 200)),  # zdržení ne
        vote(4, "2024-09-19", [pos(1, "AGAINST")], gc, result="LAPSED", counts=(0, 0)),  # propadlo ne
        vote(5, "2024-09-20", [pos(1, "AGAINST")], gc, result=None, counts=(10, 5)),  # bez výsledku ne
        vote(6, "2024-09-21", [pos(1, "AGAINST")], gc, result="REJECTED", counts=(300, 310)),  # těsné
    ]
    t = cs.compute(meps, votes)["1"]["total"]
    assert t["outcome"] == [2, 3]
    assert t["outcome_main"] == [1, 1]
    assert t["outcome_close"] == [1, 1]
    # průměr frakce ve stejných hlasováních: přijato -> pro (100), zamítnuto -> proti (50), ze 150 v každém
    assert t["group_outcome"] == [100 + 50 + 50, 450]


def test_ni_has_no_group_outcome():
    t = cs.compute([mep(1)], [vote(1, "2024-09-16", [pos(1, "FOR", "NI")], {"NI": [5, 0, 0, 0]}, result="ADOPTED", counts=(300, 200))])[
        "1"
    ]["total"]
    assert t["outcome"] == [1, 1] and t["group_outcome"] == [0, 0]


def test_close_and_decisive():
    meps = [mep(i) for i in range(1, 4)]
    cz = [pos(1, "FOR"), pos(2, "FOR"), pos(3, "AGAINST")]
    votes = [
        # 300:299 přijato; bez Čechů (2 pro, 1 proti) 298:298 -> zamítnuto => rozhodující
        vote(1, "2024-09-16", cz, result="ADOPTED", counts=(300, 299)),
        # 320:299 je těsné (rozdíl 21), bez Čechů 318:298 pořád přijato => není rozhodující
        vote(2, "2024-09-17", cz, result="ADOPTED", counts=(320, 299)),
        # 330:299 rozdíl 31 => není těsné
        vote(3, "2024-09-18", cz, result="ADOPTED", counts=(330, 299)),
        # oficiální výsledek neodpovídá prosté většině (remíza přijata) => vynecháno
        vote(4, "2024-09-19", cz, result="ADOPTED", counts=(289, 289)),
    ]
    a = cs.analyze_votes(meps, votes)
    assert a["close"]["count"] == 3 and a["close"]["ids"] == [1, 2, 4]
    assert a["decisive"] == [{"id": 1, "alternative_result": "REJECTED", "is_final": False, "vote_kind": "other"}]
    s = cs.compute(meps, votes)
    assert s["3"]["decisive"] == [{"id": 1, "position": "AGAINST"}]


def test_against_group_lists_newest_first():
    gc = {"EPP": [100, 5, 0, 0]}
    votes = [vote(i, f"2024-09-{10 + i}", [pos(1, "AGAINST")], gc, is_main=(i == 2)) for i in range(1, 4)]
    votes.append(vote(9, "2024-09-30", [pos(1, "FOR")], gc))  # s frakcí, nepočítá se
    ag = cs.compute([mep(1)], votes)["1"]["against_group"]
    assert ag["count"] == 3 and ag["count_main"] == 1
    assert [x["id"] for x in ag["recent"]] == [3, 2, 1]
    assert [x["id"] for x in ag["recent_main"]] == [2]
    assert ag["recent"][0]["group_majority"] == "FOR"


def test_cz_split_and_ranking():
    assert cs.cz_split([pos(1, "FOR"), pos(2, "AGAINST"), pos(3, "AGAINST"), pos(4, "ABSTENTION")]) == (1 / 3, 1, 2)
    assert cs.cz_split([pos(1, "FOR"), pos(2, "FOR")]) is None
    meps = [mep(i) for i in range(1, 5)]
    votes = [
        vote(1, "2024-09-16", [pos(1, "FOR"), pos(2, "AGAINST")]),  # 0,5 ze 2
        vote(2, "2024-09-17", [pos(1, "FOR"), pos(2, "FOR"), pos(3, "AGAINST"), pos(4, "AGAINST")]),  # 0,5 ze 4
        vote(3, "2024-10-30", [pos(1, "FOR"), pos(2, "FOR"), pos(3, "AGAINST")]),  # 1/3
    ]
    sp = cs.analyze_votes(meps, votes)["splits"]
    assert [x["id"] for x in sp["all"]] == [2, 1, 3]
    assert sp["last_session"]["from"] == "2024-10-30" and [x["id"] for x in sp["last_session"]["split"]] == [3]


def test_last_session_dates():
    days = ["2024-09-16", "2024-09-17", "2024-10-07", "2024-10-08", "2024-10-10"]
    assert cs.last_session_dates(days) == ["2024-10-07", "2024-10-08", "2024-10-10"]
    assert cs.last_session_dates([]) == []


def test_parties_cohesion_and_splits_skip_independent():
    party = lambda i, pid, position: {**pos(i, position), "national_party_id": pid}
    meps = [
        mep(1),
        mep(2),
        mep(3, parties=[{"org_id": "99", "short_label": "Ind.", "name": "Independent", "start": "2024-07-16", "end": None}]),
    ]
    votes = [
        vote(1, "2024-09-16", [party(1, 20, "FOR"), party(2, 20, "FOR"), party(3, 99, "FOR")], is_main=True),
        vote(2, "2024-09-17", [party(1, 20, "FOR"), party(2, 20, "AGAINST")]),
        vote(3, "2024-09-18", [party(1, 20, "FOR"), party(2, 20, "DID_NOT_VOTE")]),  # jen 1 hlasoval
    ]
    p = cs.compute_parties(meps, votes)
    assert set(p) == {"20"}
    assert p["20"]["cohesion"] == [1, 2] and p["20"]["cohesion_main"] == [1, 1]
    assert p["20"]["splits"]["count"] == 1 and p["20"]["splits"]["recent"] == [2]
    assert p["20"]["total"]["attendance"] == [5, 6]


def test_topics_level2():
    meps = [mep(1)]
    votes = [
        vote(1, "2024-09-16", [pos(1, "FOR")], topics=["3.70.03", "3.70.01"]),
        vote(2, "2024-09-17", [pos(1, "DID_NOT_VOTE")], topics=["3.70"]),
        vote(3, "2024-09-18", [pos(1, "FOR")], topics=["6.10"]),
    ]
    assert cs.top_topics(votes, 1) == ["3.70"]
    t = cs.compute(meps, votes, ["3.70"])["1"]["topics"]
    assert list(t) == ["3.70"] and t["3.70"]["attendance"] == [1, 2]


def test_cz_unity_and_strong_split():
    meps = [mep(i) for i in range(1, 5)]
    votes = [
        vote(1, "2024-09-16", [pos(1, "FOR"), pos(2, "FOR"), pos(3, "ABSTENTION")], is_main=True),  # jednotně
        vote(2, "2024-09-17", [pos(1, "FOR"), pos(2, "FOR"), pos(3, "FOR"), pos(4, "AGAINST")]),  # 1/4 < 0,3
        vote(3, "2024-09-18", [pos(1, "FOR"), pos(2, "AGAINST")]),  # 0,5 výrazný
        vote(4, "2024-09-19", [pos(1, "FOR"), pos(2, "DID_NOT_VOTE")]),  # jen 1 -> nepočítá se
    ]
    u = cs.analyze_votes(meps, votes)["unity"]
    assert (u["united"], u["considered"], u["strong_split"]) == (1, 3, 1)
    assert (u["united_final"], u["considered_final"]) == (1, 1)
    assert u["last_session"] == {"united": 1, "considered": 3, "strong_split": 1}


def test_main_metrics_use_only_final_votes():
    """Návrh na zamítnutí, mandát ani naléhavost nejsou závěrečná hlasování (review R1/R2)."""
    gc = {"EPP": [100, 5, 0, 0]}
    rej = vote(1, "2024-09-16", [pos(1, "FOR")], gc, is_main=True, result="REJECTED", counts=(83, 540))
    rej["description"], rej["amendment_subject"] = "Proposition de rejet - Am 3", "Proposal for rejection"
    mandate = vote(2, "2024-09-17", [pos(1, "DID_NOT_VOTE")], gc, is_main=True)
    mandate["description"] = "Décision d'engager des négociations interinstitutionnelles"
    final = vote(3, "2024-09-18", [pos(1, "FOR")], gc, is_main=True, result="ADOPTED", counts=(536, 101))
    final["description"], final["amendment_subject"] = "Accord provisoire - Am 2", "Provisional agreement"
    t = cs.compute([mep(1)], [rej, mandate, final])["1"]["total"]
    assert t["attendance_main"] == [1, 1]  # jen prozatímní dohoda
    assert t["outcome_main"] == [1, 1]
    assert t["attendance"] == [2, 3]  # všechna hlasování dál počítají


def test_against_group_with_czech_party_majority():
    """D3: u odchylky od frakce se zjišťuje, jak hlasovala většina české strany poslance (bez něj samotného)."""

    def p(i, position, party="MOCK_A", pid=1, group="EPP"):
        return {**pos(i, position, group), "national_party_id": pid, "national_party": party}

    gc = {"EPP": [10, 0, 0, 0]}  # většina frakce vždy PRO
    meps = [mep(1), mep(2), mep(3), mep(4)]
    votes = [
        # 1 hlasuje PROTI frakci; spolustraníci 2 a 3 také PROTI -> stejně jako strana
        vote(1, "2025-01-10", [p(1, "AGAINST"), p(2, "AGAINST"), p(3, "AGAINST"), p(4, "FOR", "MOCK_B", 2)], gc),
        # strana 1 se rozdělila 1 : 1 u ostatních -> bez většiny (None)
        vote(2, "2025-01-11", [p(1, "AGAINST"), p(2, "AGAINST"), p(3, "FOR"), p(4, "FOR", "MOCK_B", 2)], gc),
        # 4 je v jednočlenné straně: strana bez jiného hlasujícího -> None
        vote(3, "2025-01-12", [p(1, "FOR"), p(4, "AGAINST", "MOCK_B", 2)], gc),
        # spolustraník 2 nehlasoval, 3 hlasoval PRO: většina strany PRO, 1 hlasuje PROTI frakci i straně
        vote(4, "2025-01-13", [p(1, "AGAINST"), p(2, "DID_NOT_VOTE"), p(3, "FOR")], gc),
    ]
    ag = cs.compute(meps, votes, topics=[])["1"]["against_group"]
    assert ag["count"] == 3 and ag["party_known"] == 2 and ag["with_party"] == 1
    by_id = {x["id"]: x["party_majority"] for x in ag["recent"]}
    assert by_id == {1: "AGAINST", 2: None, 4: "FOR"}
    ag4 = cs.compute(meps, votes, topics=[])["4"]["against_group"]
    assert ag4["count"] == 1 and ag4["party_known"] == 0 and ag4["with_party"] == 0


def test_independent_has_no_party_majority():
    a = {**pos(1, "AGAINST"), "national_party_id": 9, "national_party": cs.INDEPENDENT}
    b = {**pos(2, "AGAINST"), "national_party_id": 9, "national_party": cs.INDEPENDENT}
    assert cs.party_majority(a, [a, b]) is None


def test_czech_titles_from_ep_open_data(tmp_path):
    """Český název hlasování = oficiální název procedury z EP Open Data (stav fetch_proposals i položky s českou účastí)."""
    import json as _json

    (tmp_path / "proposals_state.json").write_text(
        _json.dumps(
            {
                "procedures": {
                    "2023-0436": {"label": "2023/0436(COD)", "title_cs": "MOCK Práva cestujících"},
                    "2025-0803": {"label": ["2025/0803(CNS)", "2025/0803(NLE)"], "title_cs": "MOCK dva štítky"},
                    "2024-0001": {"label": "2024/0001(COD)"},
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "proposals.json").write_text(
        _json.dumps({"items": [{"kind": "procedure", "label": "2024/0002(COD)", "title": {"cs": "MOCK z položek", "en": None}}]}),
        encoding="utf-8",
    )
    titles = cs.procedure_titles(tmp_path)
    assert titles == {
        "2023/0436(COD)": "MOCK Práva cestujících",
        "2025/0803(CNS)": "MOCK dva štítky",
        "2025/0803(NLE)": "MOCK dva štítky",
        "2024/0002(COD)": "MOCK z položek",
    }
    votes = [
        {"id": 1, "title": "MOCK EN", "procedure": {"reference": "2023/0436(COD)"}},
        {"id": 2, "title": "MOCK bez procedury", "procedure": {"reference": None}},
        {"id": 3, "title": "MOCK bez názvu", "procedure": {"reference": "2024/0001(COD)"}},
    ]
    cs.apply_titles(votes, titles)
    assert votes[0]["title_cs"] == "MOCK Práva cestujících" and "title_cs" not in votes[1] and "title_cs" not in votes[2]
    assert cs.procedure_titles(tmp_path / "nic") == {}


def test_czech_titles_seed_file(tmp_path):
    """Jednorázově stažené názvy (procedure_titles_cs.json) platí, než je doplní denní běh; stav má přednost."""
    import json as _json

    (tmp_path / "procedure_titles_cs.json").write_text(
        _json.dumps(
            {
                "titles": {
                    "2023-0436": {"label": "2023/0436(COD)", "title_cs": "MOCK ze seznamu"},
                    "2024-0009": {"label": "2024/0009(COD)", "title_cs": "MOCK jen seznam"},
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "proposals_state.json").write_text(
        _json.dumps({"procedures": {"2023-0436": {"label": "2023/0436(COD)", "title_cs": "MOCK ze stavu"}}}), encoding="utf-8"
    )
    titles = cs.procedure_titles(tmp_path)
    assert titles == {"2023/0436(COD)": "MOCK ze stavu", "2024/0009(COD)": "MOCK jen seznam"}
