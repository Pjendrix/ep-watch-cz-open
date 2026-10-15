import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_web as bw  # noqa: E402


def mep(i, end=None, group="PPE", party="20"):
    return {
        "id": i, "name": f"MOCK {i}", "given_name": "MOCK", "family_name": str(i), "sort_label": str(i),
        "gender": "FEMALE", "photo_url": None, "mandates": [{"start": "2024-07-16", "end": end}],
        "groups": [{"code": group, "short_label": group, "start": "2024-07-16", "end": None}],
        "parties": [{"org_id": party, "short_label": "MOCK_P", "start": "2024-07-16", "end": None}],
        "committees": [],
    }


def vote(vid, date, positions, is_main=True, title="MOCK vote", description=None):
    return {"id": vid, "date": date, "title": title, "reference": "MOCK-REF", "description": description,
            "amendment_number": None, "result": "ADOPTED", "is_main": is_main, "procedure": {},
            "counts": {"for": 300, "against": 299, "abstention": 0, "did_not_vote": 0},
            "group_counts": {}, "topics": {"oeil": [{"code": "3.70.03"}]}, "cz_positions": [
                {"member_id": i, "position": p, "group_code": "EPP", "national_party_id": 20} for i, p in positions]}


def metrics():
    return {"attendance": [1, 2], "attendance_main": [1, 1], "group_loyalty": [1, 1], "cz_agreement": [0, 1],
            "positions": {"FOR": 1, "AGAINST": 0, "ABSTENTION": 0, "DID_NOT_VOTE": 1}}


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    (d / "votes").mkdir(parents=True)
    meps = [mep(1), mep(2, end="2024-09-30")]
    (d / "meps.json").write_text(json.dumps({"meps": meps}), encoding="utf-8")
    stats = {"sources": {"votes": {"release": "MOCK"}}, "period": {"from": "2024-09-16", "to": "2024-10-16"},
             "votes_total": 4, "definitions": {"attendance": "MOCK"},
             "meps": {"1": {"total": metrics(), "monthly": {"2024-09": metrics()}, "pairwise": {"2": [1, 1]},
                            "topics": {"3.70": metrics()},
                            "against_group": {"count": 1, "count_main": 0, "recent": [
                                {"id": 2, "is_final": False, "position": "AGAINST", "group_code": "EPP",
                                 "group_majority": "FOR"}], "recent_main": []},
                            "decisive": [{"id": 1, "position": "FOR"}]},
                      "2": {"total": metrics(), "monthly": {}, "pairwise": {"1": [1, 1]}}},
             "topics": [{"code": "3.70", "label": "MOCK environment", "votes": 1}],
             "parties": {"20": {"total": metrics(), "cohesion": [1, 2], "cohesion_main": [1, 1],
                                "splits": {"count": 1, "count_main": 0, "recent": [2], "recent_main": []}}},
             "votes_analysis": {
                 "close": {"count": 3, "count_main": 2, "ids": [1, 2, 3]},
                 "decisive": [{"id": 1, "alternative_result": "REJECTED"}],
                 "splits": {"count": 1, "count_main": 0,
                            "all": [{"id": 2, "date": "2024-09-17", "is_final": False, "split": 0.5, "for": 1, "against": 1}],
                            "main": [],
                            "last_session": {"from": "2024-10-16", "to": "2024-10-16", "votes": 1, "split": []}}}}
    (d / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    (d / "manual").mkdir()
    (d / "manual" / "topics_cs.json").write_text(json.dumps({"labels": {"3.70": "MOCK životní prostředí"}}),
                                                 encoding="utf-8")
    (d / "parties.json").write_text(json.dumps([
        {"id": 20, "short_label": "MOCK_P", "name": "MOCK strana", "independent": False, "color": None, "logo": None},
        {"id": 99, "short_label": "Ind.", "name": "Independent", "independent": True, "color": None, "logo": None},
    ]), encoding="utf-8")
    votes = {
        "2024-09": [vote(1, "2024-09-16", [(1, "FOR"), (2, "FOR")]),
                    vote(2, "2024-09-17", [(1, "DID_NOT_VOTE"), (2, "AGAINST")], is_main=False, title=None)],
        "2024-10": [vote(3, "2024-10-16", [(1, "AGAINST"), (2, "DID_NOT_VOTE")]),  # 2 už není v mandátu
                    vote(4, "2024-10-17", [(1, "FOR")], description="Proposition de rejet")],
    }
    index = {"source": {"release": "MOCK"}, "groups": [],
             "months": [{"month": k, "votes": len(v)} for k, v in votes.items()]}
    (d / "votes" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    for k, v in votes.items():
        (d / "votes" / f"{k}.json").write_text(json.dumps({"votes": v}), encoding="utf-8")
    return d


def test_search_rows_and_cz_counts_only_in_mandate(data_dir):
    bw.run(data_dir, "2024-11-01")
    search = json.loads((data_dir / "votes" / "search.json").read_text(encoding="utf-8"))
    rows = [dict(zip(search["fields"], r)) for r in search["rows"]]
    assert [r["id"] for r in rows] == [1, 2, 3, 4]
    assert rows[0]["cz"] == [2, 0, 0, 0]
    assert rows[1]["title"] == "MOCK-REF"  # bez názvu -> reference
    assert rows[2]["cz"] == [0, 1, 0, 0]   # poslanec 2 po konci mandátu se nepočítá
    assert rows[2]["month"] == "2024-10"
    # typ hlasování se dopočítá i pro starší soubory bez pole vote_kind
    assert [r["vote_kind"] for r in rows] == ["final", "other", "final", "rejection"]
    assert rows[3]["description_cs"] == "Návrh na zamítnutí"
    assert search["kind_labels"]["rejection"] == "návrh na zamítnutí"
    assert rows[0]["topics"] == ["3.70"] and search["topic_labels"] == {"3.70": "MOCK životní prostředí"}


def test_profile_contains_everything_for_page(data_dir):
    bw.run(data_dir, "2024-11-01")
    prof = json.loads((data_dir / "meps" / "1.json").read_text(encoding="utf-8"))
    assert prof["mep"]["id"] == 1
    assert prof["total"]["attendance"] == [1, 2]
    assert list(prof["monthly"]) == ["2024-09"]
    assert [(p["id"], p["same"], p["total"], p["name"]) for p in prof["pairwise"]] == [(2, 1, 1, "MOCK 2")]
    # jen závěrečná hlasování (návrh na zamítnutí 4 ne), nejnovější první
    assert [(v["id"], v["position"]) for v in prof["recent_main_votes"]] == [(3, "AGAINST"), (1, "FOR")]
    prof2 = json.loads((data_dir / "meps" / "2.json").read_text(encoding="utf-8"))
    assert [v["id"] for v in prof2["recent_main_votes"]] == [1]  # hlasování 3 je po konci mandátu


def test_overview(data_dir):
    bw.run(data_dir, "2024-11-01")
    ov = json.loads((data_dir / "overview.json").read_text(encoding="utf-8"))
    assert ov["votes_total"] == 4 and ov["definitions"] == {"attendance": "MOCK"}
    first = ov["meps"][0]
    assert first["group"] == {"code": "PPE", "short_label": "PPE"}
    assert first["party"] == {"id": 20, "short_label": "MOCK_P"}
    assert first["total"]["attendance"] == [1, 2]
    assert "committees" not in first  # souhrn je odlehčený
    assert [m["short_mandate"] for m in ov["meps"]] == [False, False]


def test_short_mandate():
    assert bw.mandate_days([{"start": "2024-07-16", "end": "2024-07-31"}], "2026-10-14") == 16
    assert bw.mandate_days([{"start": "2026-10-01", "end": None}], "2026-10-14") == 14
    assert bw.mep_summary(mep(1, end="2024-07-31"), "2026-10-14")["short_mandate"] is True


def test_missing_stats_raises(data_dir):
    stats = json.loads((data_dir / "stats.json").read_text(encoding="utf-8"))
    del stats["meps"]["2"]
    (data_dir / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    with pytest.raises(bw.FormatError, match="nemá poslance"):
        bw.run(data_dir, "2024-11-01")


def test_current_membership():
    items = [{"start": "2024-07-16", "end": "2025-01-31"}, {"start": "2025-02-01", "end": None}]
    assert bw.current(items, "2024-12-01") is items[0]
    assert bw.current(items, "2025-06-01") is items[1]
    assert bw.current([{"start": "2024-07-16", "end": "2024-07-31"}], "2025-01-01")["end"] == "2024-07-31"
    assert bw.current([], "2025-01-01") is None


def test_profile_phase_c_sections(data_dir):
    bw.run(data_dir, "2024-11-01")
    prof = json.loads((data_dir / "meps" / "1.json").read_text(encoding="utf-8"))
    assert prof["against_group"]["count"] == 1
    assert prof["against_group"]["recent"][0]["title"] == "MOCK-REF"  # hlasování 2 nemá název
    assert prof["against_group"]["recent"][0]["group_majority"] == "FOR"
    assert [(d["id"], d["position"]) for d in prof["decisive"]] == [(1, "FOR")]
    assert prof["topics"][0]["code"] == "3.70" and prof["topics"][0]["label"] == "MOCK environment"
    assert prof["topics"][0]["label_cs"] == "MOCK životní prostředí"


def test_decisive_splits_and_parties_files(data_dir):
    bw.run(data_dir, "2024-11-01")
    dec = json.loads((data_dir / "decisive.json").read_text(encoding="utf-8"))
    assert dec["close_count"] == 3 and dec["votes"][0]["alternative_result"] == "REJECTED"
    assert [p["member_id"] for p in dec["votes"][0]["positions"]] == [1, 2]
    sp = json.loads((data_dir / "splits.json").read_text(encoding="utf-8"))
    assert sp["all"][0]["id"] == 2 and sp["all"][0]["split"] == 0.5
    assert sp["all"][0]["positions"] == {"1": "DID_NOT_VOTE", "2": "AGAINST"}
    assert sp["all"][0]["groups"] == {"1": "EPP", "2": "EPP"}  # frakce k datu hlasování
    idx = json.loads((data_dir / "parties" / "index.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in idx["parties"]] == [20]  # nezávislí nejsou strana
    page = json.loads((data_dir / "parties" / "20.json").read_text(encoding="utf-8"))
    assert page["members"] == 2 and page["cohesion"] == [1, 2]
    assert page["splits"][0]["id"] == 2 and len(page["splits"][0]["positions"]) == 2
    assert not (data_dir / "parties" / "99.json").exists()


def test_session_and_agreement(data_dir):
    bw.run(data_dir, "2024-11-01")
    ses = json.loads((data_dir / "session.json").read_text(encoding="utf-8"))
    assert (ses["from"], ses["to"], ses["votes"], ses["main"]) == ("2024-10-16", "2024-10-16", 1, 1)
    assert ses["close_count"] == 1 and ses["decisive"] == [] and ses["top_splits"] == []
    ag = json.loads((data_dir / "agreement.json").read_text(encoding="utf-8"))
    assert [m["id"] for m in ag["meps"]] == [1, 2]
    assert ag["matrix"]["1"] == {"2": [1, 1]}


def test_profile_benchmarks(data_dir):
    bench = {"source": {"release": "MOCK"}, "definition": "MOCK", "min_votes": 100,
             "ep": {"meps": 700, "attendance": 0.9, "attendance_main": 0.91, "group_loyalty": 0.93},
             "groups": {"EPP": {"meps": 180, "attendance": 0.88, "attendance_main": 0.9, "group_loyalty": 0.95}}}
    (data_dir / "benchmarks.json").write_text(json.dumps(bench), encoding="utf-8")
    bw.run(data_dir, "2024-11-01")
    prof = json.loads((data_dir / "meps" / "1.json").read_text(encoding="utf-8"))
    assert prof["benchmarks"]["ep"]["attendance"] == 0.9
    assert prof["benchmarks"]["group_code"] == "EPP" and prof["benchmarks"]["group"]["group_loyalty"] == 0.95


def test_profile_without_benchmarks(data_dir):
    bw.run(data_dir, "2024-11-01")
    assert json.loads((data_dir / "meps" / "1.json").read_text(encoding="utf-8"))["benchmarks"] is None


def test_work_ranking_file(data_dir):
    own = {"source": "MOCK", "updated": "2026-10-15", "complete": True, "type_labels": {},
           "meps": {"1": {"summary": {}, "items": [], "passed": {"lead_adopted": 2, "shadow_adopted": 1},
                    "roles": {"lead_reports": 3, "lead_opinions": 1, "motions_signed": 7,
                              "delegation": {"tiers": {"lead_reports": "top"}, "of": 1, "mandate_from": None}}}}}
    (data_dir / "own_work.json").write_text(json.dumps(own), encoding="utf-8")
    bw.run(data_dir, "2024-11-01")
    work = json.loads((data_dir / "work.json").read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in work["meps"]}
    assert rows[1]["lead_adopted"] == 2 and rows[1]["lead_reports"] == 3 and rows[1]["motions_signed"] == 7
    assert rows[1]["shadow_opinions"] == 0 and rows[1]["delegation"]["tiers"]["lead_reports"] == "top"
    assert rows[2]["lead_reports"] == 0 and rows[2]["delegation"] is None  # bez dat nic nevymýšlíme


def test_functions_only_current_chairs_and_bureau():
    m = {"committees": [
            {"role": "CHAIR", "code": "AGRI", "name_cs": "Zemědělství", "start": "2024-07-23", "end": None},
            {"role": "MEMBER", "code": "ENVI", "name_cs": "ŽP", "start": "2024-07-23", "end": None},
            {"role": "CHAIR_VICE", "code": "ECON", "name_cs": "Hosp.", "start": "2024-07-23", "end": "2025-01-01"}],
         "groups": [{"role": "MEMBER_BUREAU", "code": "ECR", "name_cs": "ECR", "start": "2024-07-16", "end": None},
                    {"role": "MEMBER", "code": "ECR", "name_cs": "ECR", "start": "2024-07-16", "end": None}]}
    f = bw.functions(m, "2026-01-01")
    assert [(x["kind"], x["role"], x["code"]) for x in f] == [("committee", "CHAIR", "AGRI"), ("group", "MEMBER_BUREAU", "ECR")]


def test_mep_votes_only_in_mandate():
    mep = {"id": 1, "mandates": [{"start": "2024-07-16", "end": "2024-09-30"}]}
    votes = [
        {"id": 10, "date": "2024-09-10", "cz_positions": [{"member_id": 1, "position": "FOR"}, {"member_id": 2, "position": "AGAINST"}]},
        {"id": 11, "date": "2024-09-11", "cz_positions": [{"member_id": 1, "position": "DID_NOT_VOTE"}]},
        {"id": 12, "date": "2024-10-02", "cz_positions": [{"member_id": 1, "position": "AGAINST"}]},  # po mandátu
        {"id": 13, "date": "2024-09-12", "cz_positions": [{"member_id": 2, "position": "FOR"}]},       # poslanec nehlasuje v datech
    ]
    assert bw.mep_votes(mep, votes) == {"ids": [10, 11], "positions": "FN"}


def test_vote_roles_from_own_work():
    own = {"meps": {"1": {"items": [
        {"type": "report", "role": "RAPPORTEUR", "vote_id": 10, "report": "A10-0001/2025", "label": "2025/0001(COD)"},
        {"type": "motion", "role": "AUTHOR", "vote_id": 10},                                        # usnesení se nepočítá
        {"type": "report", "role": "RAPPORTEUR", "vote_id": None}]},                                 # bez hlasování
        "2": {"items": [{"type": "shadow_report", "role": "RAPPORTEUR_SHADOW", "vote_id": 10, "report": "A10-0001/2025", "label": "2025/0001(COD)"}]},
        "3": {"items": [{"type": "report", "role": "RAPPORTEUR_CO", "vote_id": 9, "report": "A10-0002/2025", "label": "x"}]}}}
    r = bw.build_vote_roles(own)
    assert list(r) == ["9", "10"]
    assert [(x["mep_id"], x["role"]) for x in r["10"]] == [(1, "rapporteur"), (2, "shadow")]  # zpravodaj před stínovým
    assert r["9"][0]["role"] == "co" and bw.build_vote_roles(None) == {}
