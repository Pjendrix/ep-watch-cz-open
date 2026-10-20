import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_votes as fv  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "htv"


@pytest.fixture
def csv_dir(tmp_path):
    d = tmp_path / "htv"
    shutil.copytree(FIXTURES, d)
    return d


def edit(csv_dir, table, old, new):
    p = csv_dir / f"{table}.csv"
    p.write_text(p.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")


def test_run_filters_term_and_country(csv_dir, tmp_path):
    out = tmp_path / "out"
    months = fv.run(csv_dir, out, release="MOCK_TAG", group_composition=False)
    bench = json.loads((out.parent / "benchmarks.json").read_text(encoding="utf-8"))
    assert bench["source"] == {"release": "MOCK_TAG"} and "ep" in bench and "rank" not in json.dumps(bench)

    assert sorted(months) == ["2024-07", "2024-09"]
    assert sorted(p.name for p in out.iterdir()) == ["2024-07.json", "2024-09.json", "index.json"]

    july = json.loads((out / "2024-07.json").read_text(encoding="utf-8"))
    assert july["source"]["release"] == "MOCK_TAG"
    assert [v["id"] for v in july["votes"]] == [2]  # hlasování 1 je před 16. 7. 2024
    v = july["votes"][0]
    assert v["is_main"] is True
    assert v["result"] == "ADOPTED"
    assert v["counts"] == {"for": 400, "against": 200, "abstention": 50, "did_not_vote": 70}
    assert v["source_url"] == "https://howtheyvote.eu/votes/2"
    # jen čeští poslanci, seřazení podle ID
    assert [p["member_id"] for p in v["cz_positions"]] == [100, 200]
    assert v["cz_positions"][1]["position"] == "DID_NOT_VOTE"
    assert v["topics"]["eurovoc"] == [
        {"code": "5", "label": "MOCK energy"},
        {"code": "6", "label": "MOCK climate"},
    ]
    assert v["topics"]["oeil"] == [{"code": "3.70", "label": "MOCK environment"}]
    assert v["topics"]["committees"] == ["ENVI"]


def test_group_and_party_taken_per_vote(csv_dir, tmp_path):
    months = fv.run(csv_dir, tmp_path / "out", release=None, group_composition=False)
    sept = {v["id"]: v for v in months["2024-09"]["votes"]}
    p200 = sept[3]["cz_positions"][1]
    # v červenci byl 200 v PFE se stranou, v září nezařazený bez strany
    assert p200 == {"member_id": 200, "position": "AGAINST", "group_code": "NI", "national_party_id": None, "national_party": None}


def test_missing_values_are_null_not_guessed(csv_dir, tmp_path):
    months = fv.run(csv_dir, tmp_path / "out", release=None, group_composition=False)
    v4 = {v["id"]: v for v in months["2024-09"]["votes"]}[4]
    assert v4["result"] is None
    assert v4["reference"] is None
    assert v4["topics"] == {"eurovoc": [], "oeil": [], "geo": [], "committees": []}


@pytest.mark.parametrize(
    "table,old,new,msg",
    [
        ("votes", "display_title,", "title,", "chybí sloupce"),
        ("member_votes", ",position,", ",vote,", "chybí sloupce"),
        ("member_votes", "DID_NOT_VOTE", "ABSENT", "neočekávaná pozice"),
        ("votes", ",REJECTED,", ",FAILED,", "neočekávaný výsledek"),
        ("votes", "2024-09-16 17:00:00", "16.9.2024", "neplatný timestamp"),
        ("votes", ",False,", ",maybe,", "is_main"),
    ],
)
def test_format_changes_raise(csv_dir, tmp_path, table, old, new, msg):
    edit(csv_dir, table, old, new)
    with pytest.raises(fv.FormatError, match=msg):
        fv.run(csv_dir, tmp_path / "out", release=None, group_composition=False)


def test_duplicate_member_vote_raises(csv_dir, tmp_path):
    p = csv_dir / "member_votes.csv"
    p.write_text(p.read_text(encoding="utf-8") + "4,200,FOR,CZE,NI,NI,,\n", encoding="utf-8")
    with pytest.raises(fv.FormatError, match="duplicitní"):
        fv.run(csv_dir, tmp_path / "out", release=None, group_composition=False)


def test_missing_file_raises(csv_dir, tmp_path):
    (csv_dir / "geo_areas.csv").unlink()
    with pytest.raises(fv.FormatError, match="geo_areas"):
        fv.run(csv_dir, tmp_path / "out", release=None, group_composition=False)


def test_main_returns_error_code_on_format_change(csv_dir, tmp_path):
    edit(csv_dir, "votes", "display_title,", "title,")
    assert fv.main(["--csv-dir", str(csv_dir), "--out-dir", str(tmp_path / "out")]) == 2


class FakeResponse:
    def __init__(self, status, location):
        self.status_code = status
        self.headers = {"Location": location} if location else {}


class FakeSession:
    def __init__(self, response):
        self.response = response

    def head(self, *a, **kw):
        return self.response


def test_resolve_release_tag():
    loc = "https://github.com/HowTheyVote/data/releases/download/2026-10-10/votes.csv.gz"
    assert fv.resolve_release_tag(FakeSession(FakeResponse(302, loc))) == "2026-10-10"
    assert fv.resolve_release_tag(FakeSession(FakeResponse(200, None))) is None


def test_table_url_pins_resolved_tag():
    assert fv.table_url("votes", "2026-10-10") == "https://github.com/HowTheyVote/data/releases/download/2026-10-10/votes.csv.gz"
    assert fv.table_url("votes", None) == f"{fv.BASE_URL}/votes.csv.gz"


def test_group_counts_cover_all_countries(csv_dir, tmp_path):
    months = fv.run(csv_dir, tmp_path / "out", release=None, group_composition=False)
    v2 = months["2024-07"]["votes"][0]
    # [pro, proti, zdržel se, nehlasoval]; SD má jen slovenského poslance
    assert v2["group_counts"] == {"EPP": [1, 0, 0, 0], "PFE": [0, 0, 0, 1], "SD": [0, 1, 0, 0]}


def test_index_lists_months_and_used_groups(csv_dir, tmp_path):
    out = tmp_path / "out"
    fv.run(csv_dir, out, release="MOCK_TAG", group_composition=False)
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["months"] == [{"month": "2024-07", "votes": 1}, {"month": "2024-09", "votes": 2}]
    assert [g["code"] for g in index["groups"]] == ["EPP", "NI", "PFE", "SD"]  # GREEN_EFA nehlasovali
    assert index["source"]["release"] == "MOCK_TAG"
    assert index["oeil_subjects"] == {"3.70": "MOCK environment"}


@pytest.mark.parametrize("result", ["LAPSED", "WITHDRAWN"])
def test_lapsed_and_withdrawn_are_valid(csv_dir, tmp_path, result):
    edit(csv_dir, "votes", ",REJECTED,", f",{result},")
    months = fv.run(csv_dir, tmp_path / "out", release=None, group_composition=False)
    assert {v["id"]: v["result"] for v in months["2024-09"]["votes"]}[3] == result


def test_release_check(tmp_path):
    """E1: nový export = známý tag, který se liší od dat v repu; neznámý tag běh nespouští."""
    assert fv.release_is_new("2026-10-17", "2026-10-10")
    assert not fv.release_is_new("2026-10-10", "2026-10-10")
    assert not fv.release_is_new(None, "2026-10-10")
    assert fv.release_is_new("2026-10-17", None)
    assert fv.stored_release(tmp_path) is None
    (tmp_path / "index.json").write_text('{"source": {"release": "2026-10-10"}}', encoding="utf-8")
    assert fv.stored_release(tmp_path) == "2026-10-10"
