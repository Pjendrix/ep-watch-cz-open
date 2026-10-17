"""Úvodní stránka (data/home.json): pět nejnovějších závěrečných hlasování bez výběru, hlasy k datu hlasování, fakta z JSON."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_home as bh  # noqa: E402
import build_web as bw  # noqa: E402
from test_build_web import data_dir  # noqa: E402,F401  (sdílená fixture s MOCK daty)


def v(vid, date, kind, ts="T10"):
    return {"id": vid, "date": date, "timestamp": date + ts, "vote_kind": kind, "title": f"MOCK {vid}"}


def test_latest_final_picks_five_newest_final_only():
    votes = [v(i, f"2024-10-{10 + i:02d}", "final") for i in range(1, 8)]
    votes += [v(50, "2024-10-30", "amendment"), v(51, "2024-10-31", "rejection"), v(52, "2024-10-29", "provisional_agreement")]
    got = [x["id"] for x in bh.latest_final(votes)]
    assert got == [52, 7, 6, 5, 4]  # bez dílčích a zamítnutí, od nejnovějšího
    # stejný den: podle času, deterministicky
    same = [v(1, "2024-10-10", "final", "T09"), v(2, "2024-10-10", "final", "T11")]
    assert [x["id"] for x in bh.latest_final(same)] == [2, 1]


def _with_extra_files(d):
    bw.run(d, "2024-10-20")
    (d / "splits.json").write_text(json.dumps({"unity": {"considered": 4, "united_final": 1, "considered_final": 2}}), encoding="utf-8")
    (d / "decisive.json").write_text(json.dumps({"votes": [{"id": 1}]}), encoding="utf-8")
    (d / "work_hub.json").write_text(
        json.dumps({"updated": "2024-10-20", "totals": {"meps": 2, "speeches": 5, "questions": 3, "reports_lead": 1}}), encoding="utf-8"
    )


def test_home_positions_at_vote_date_and_counts(data_dir):
    _with_extra_files(data_dir)
    home = bh.build(data_dir)
    ids = [x["id"] for x in home["votes"]]
    assert ids and 2 not in ids and 4 not in ids  # 2 dílčí, 4 návrh na zamítnutí
    newest = home["votes"][0]
    assert newest["id"] == 3
    # tečky = poslanci v mandátu v den nejnovějšího hlasování (poslanec 2 skončil 30. 9.)
    assert [p["id"] for p in newest["ppl"]] == [1]
    for x in home["votes"]:
        assert [p["id"] for p in x["ppl"]] == [1]  # stejné pořadí ve všech hlasováních
        assert sum(x["counts"].values()) == len(x["ppl"])
    assert newest["ppl"][0]["pos"] == "A"
    older = next(x for x in home["votes"] if x["id"] == 1)
    assert older["ppl"][0]["pos"] == "F" and older["counts"]["F"] == 1
    f = home["facts"]
    assert f["votes_total"] == 4 and f["united_final"] == 1 and f["considered_final"] == 2 and f["decisive"] == 1
    assert f["work"]["meps"] == 2 and f["meps_active"] == 1


def test_mep_out_of_mandate_is_x(data_dir):
    _with_extra_files(data_dir)
    # poslanec 1 chybí v cz_positions hlasování 1 (jako by tehdy nebyl v mandátu)
    p = data_dir / "votes" / "2024-09.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["votes"][0]["cz_positions"] = [x for x in doc["votes"][0]["cz_positions"] if x["member_id"] != 1]
    p.write_text(json.dumps(doc), encoding="utf-8")
    home = bh.build(data_dir)
    older = next(x for x in home["votes"] if x["id"] == 1)
    assert older["ppl"][0]["pos"] == "X" and older["counts"]["X"] == 1


def test_real_data_consistency():
    """Na skutečných datech: 5 hlasování, F+A+B+N+X = počet teček, pozice = cz_positions k datu hlasování."""
    root = Path(__file__).resolve().parent.parent / "data"
    if not (root / "home.json").exists():
        return
    home = json.loads((root / "home.json").read_text(encoding="utf-8"))
    assert len(home["votes"]) == 5
    n = len(home["votes"][0]["ppl"])
    for x in home["votes"]:
        assert sum(x["counts"].values()) == n
        month = json.loads((root / "votes" / f"{x['month']}.json").read_text(encoding="utf-8"))
        src = next(y for y in month["votes"] if y["id"] == x["id"])
        pos = {p["member_id"]: bh.POS_CODE[p["position"]] for p in src["cz_positions"]}
        assert all(p["pos"] == pos.get(p["id"], "X") for p in x["ppl"])
    splits = json.loads((root / "splits.json").read_text(encoding="utf-8"))["unity"]
    assert home["facts"]["votes_total"] == splits["considered"] and home["facts"]["united_final"] == splits["united_final"]
