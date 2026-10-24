import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_preliminary  # noqa: E402
import preliminary  # noqa: E402
from preliminary import FormatError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
DAY = "2026-10-22"
# výřez skutečné odpovědi EP API (GET /meetings/MTG-PL-2026-10-22/decisions, jazyky zkrácené na cs/en)
DECISIONS = json.loads((FIX / "ep" / "decisions_MTG-PL-2026-10-22.json").read_text(encoding="utf-8"))
# tatáž hlasování z exportu HowTheyVote 2026-10-24 (id, is_main, počty, hlasy Čechů)
HTV = {v["id"]: v for v in json.loads((FIX / "htv" / "votes_2026-10-22_sample.json").read_text(encoding="utf-8"))["votes"]}
MEPS_PATH = ROOT / "data" / "meps.json"
MEPS = json.loads(MEPS_PATH.read_text(encoding="utf-8"))["meps"] if MEPS_PATH.exists() else []
EP_TO_CODE = {"PPE": "EPP", "VERTS-ALE": "GREEN_EFA"}


def parsed():
    return preliminary.parse_decisions(json.loads(json.dumps(DECISIONS)), DAY)


def built():
    if not MEPS:
        pytest.skip("bez data/meps.json (export do veřejného repa)")
    return preliminary.day_file(DAY, parsed(), MEPS, EP_TO_CODE, "2026-10-22T23:30+02:00")


def test_only_rollcall_votes_with_voters():
    ids = {v["id"] for v in parsed()}
    # ruční hlasování a propadlé (LAPSED) jmenovité hlasování se vynechají
    assert ids == set(HTV)


def test_counts_match_lists_and_howtheyvote():
    for v in built()["votes"]:
        h = HTV[v["id"]]["counts"]
        assert v["counts"] == {"for": h["for"], "against": h["against"], "abstention": h["abstention"]}


def test_czech_positions_match_howtheyvote():
    for v in built()["votes"]:
        mine = {r[0]: r[1] for r in v["cz"]}
        theirs = {p["member_id"]: p["position"] for p in HTV[v["id"]]["cz_positions"]}
        assert mine == theirs, v["id"]


def test_main_rule_matches_howtheyvote():
    for v in built()["votes"]:
        assert v["main"] == HTV[v["id"]]["is_main"], v["label"]


def test_refs_contain_howtheyvote_reference():
    for v in built()["votes"]:
        assert HTV[v["id"]]["reference"] in v["refs"]


def test_corrections_are_listed_but_do_not_change_vote():
    v = next(x for x in built()["votes"] if x["id"] == 199569)
    assert v["corrections"] == {"256840": "ABSTENTION", "256847": "ABSTENTION"}
    pos = {r[0]: r[1] for r in v["cz"]}
    assert pos[256840] != "ABSTENTION" and pos[256847] != "ABSTENTION"  # zaznamenaný hlas zůstává


def test_group_at_vote_date_from_ep():
    # Konečná (23699): v EP API PfE od 21. 10. 2026 (HowTheyVote ji 22. 10. ještě vedl jako NI)
    v = built()["votes"][0]
    assert {r[0]: r[2] for r in v["cz"]}[23699] == "PFE"


def test_only_meps_in_mandate():
    v = built()["votes"][0]
    ids = {r[0] for r in v["cz"]}
    assert len(ids) == 21
    ended = [m["id"] for m in MEPS if all(md["end"] and md["end"] < DAY for md in m["mandates"])]
    assert ended and not ids & set(ended)


def test_count_mismatch_raises():
    bad = json.loads(json.dumps(DECISIONS))
    x = next(x for x in bad["data"] if x.get("had_voter_favor"))
    x["number_of_votes_favor"] = str(int(x["number_of_votes_favor"]) + 1)
    with pytest.raises(FormatError, match="number_of_votes_favor"):
        preliminary.parse_decisions(bad, DAY)


def test_missing_field_raises():
    bad = json.loads(json.dumps(DECISIONS))
    x = next(x for x in bad["data"] if x["decision_method"] == preliminary.ROLLCALL)
    del x["notation_votingId"]
    with pytest.raises(FormatError, match="notation_votingId"):
        preliminary.parse_decisions(bad, DAY)


def test_bad_person_id_raises():
    bad = json.loads(json.dumps(DECISIONS))
    x = next(x for x in bad["data"] if x.get("had_voter_favor"))
    x["had_voter_favor"][0] = "MOCK_osoba"
    with pytest.raises(FormatError, match="identifikátor"):
        preliminary.parse_decisions(bad, DAY)


def test_wrong_day_raises():
    with pytest.raises(FormatError):
        preliminary.parse_decisions(DECISIONS, "2026-10-21")


def test_doc_refs_and_agenda_ref():
    assert preliminary.doc_refs("RC-B10-0476/2026 – § 1/1; A10-0276/2026") == ["RC-B10-0476/2026", "A10-0276/2026"]
    assert preliminary.agenda_ref("A-10-2026-0265") == "A10-0265/2026"
    assert preliminary.agenda_ref("C-10-2025-0324") == "C10-0324/2025"
    assert preliminary.agenda_ref("MOCK") is None


def test_check_day_accepts_built_file():
    preliminary.check_day(built())
    bad = built()
    bad["votes"][0]["cz"][0][1] = "MOCK"
    with pytest.raises(FormatError):
        preliminary.check_day(bad)


def test_pending_and_stale_after_new_export(tmp_path):
    d = tmp_path / "preliminary"
    d.mkdir()
    for day in ("2026-10-21", "2026-10-22", "2026-11-11"):
        (d / f"{day}.json").write_text("{}", encoding="utf-8")
    (d / "README.txt").write_text("", encoding="utf-8")
    assert preliminary.pending_days(d, "2026-10-20") == ["2026-10-21", "2026-10-22", "2026-11-11"]
    # simulovaný nový export HowTheyVote s hlasováními do 22. 10.: ty dny zmizí z webu a smažou se
    assert preliminary.pending_days(d, "2026-10-22") == ["2026-11-11"]
    assert [p.name for p in preliminary.stale_files(d, "2026-10-22")] == ["2026-10-21.json", "2026-10-22.json"]
    assert preliminary.stale_files(d, None) == []


def test_home_items_pick_rule_and_rest():
    day = built()
    radar = {
        "session": {
            "items": [
                {"id": "MOCK_1", "title_cs": "MOCK chemické výrobky", "docs": ["A-10-2026-0104"]},
                {"id": "MOCK_2", "title_cs": "MOCK benchmarky", "docs": ["C-10-2026-0999", "A-10-2026-0276"]},
            ]
        }
    }
    picked, rest = preliminary.home_items([day], radar, ["MOCK_2"])
    assert [p["title"] for p in picked] == ["MOCK benchmarky"]
    assert {v["id"] for v in picked[0]["votes"]} == {199470, 199560}
    assert all(v["main"] for v in rest) and not {v["id"] for v in rest} & {199470, 199560}
    assert next(v for v in rest if v["id"] == 198430)["title"] == "MOCK chemické výrobky"


def test_due_only_on_sitting_days_and_day_after():
    sittings = ["2026-11-11", "2026-11-12"]
    assert fetch_preliminary.is_due(sittings, "2026-10-22", "2026-11-11")
    assert fetch_preliminary.is_due(sittings, "2026-10-22", "2026-11-13")  # dohnat večerní hlasování
    assert not fetch_preliminary.is_due(sittings, "2026-10-22", "2026-11-14")
    assert not fetch_preliminary.is_due(sittings, "2026-10-22", "2026-11-10")
    assert not fetch_preliminary.is_due(sittings, "2026-11-12", "2026-11-13")  # HowTheyVote už má vše
    assert fetch_preliminary.due_days(sittings, "2026-11-11", "2026-11-13") == ["2026-11-12"]
