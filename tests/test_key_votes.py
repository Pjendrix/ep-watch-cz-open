import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import key_votes as kv  # noqa: E402

MEPS = {
    1: {"id": 1, "mandates": [{"start": "2024-07-16", "end": None}]},
    2: {"id": 2, "mandates": [{"start": "2024-07-16", "end": None}]},
    3: {"id": 3, "mandates": [{"start": "2024-07-16", "end": None}]},
}


def vote(i, date, kind="final", n_for=300, n_against=200, result="ADOPTED", proc="COD", cz=("FOR", "FOR", "FOR")):
    return {
        "id": i,
        "date": date,
        "vote_kind": kind,
        "is_main": True,
        "title": f"MOCK {i}",
        "result": result,
        "counts": {"for": n_for, "against": n_against, "abstention": 0, "did_not_vote": 0},
        "procedure": {"type": proc, "reference": f"MOCK/{i}"},
        "cz_positions": [{"member_id": m, "position": p, "group_code": "EPP"} for m, p in zip((1, 2, 3), cz, strict=False)],
    }


VOTES = [
    vote(1, "2025-01-10"),  # starší než 12 měsíců od posledního
    vote(2, "2025-12-01", proc="INI", cz=("FOR", "AGAINST", "FOR")),  # nelegislativní, Češi rozdělení 2 : 1
    vote(3, "2026-02-03", kind="provisional_agreement", n_for=201, n_against=200),  # zákon, těsné
    vote(4, "2026-02-04", kind="amendment"),  # není závěrečné: do žádného seznamu
    vote(5, "2026-02-10", proc="RSP", result="REJECTED", n_for=100, n_against=400, cz=("FOR", "FOR", "AGAINST")),  # Češi pro, zamítnuto
]


def build():
    return kv.build_key_votes(VOTES, MEPS)


def ids(r, p, name):
    return [x["id"] for x in r["lists"][p][name]["items"]]


def test_periods_relative_to_last_vote():
    s = kv.period_starts(VOTES)
    assert s["all"] is None and s["session"] == "2026-02-10" and s["m3"] == "2025-11-10" and s["m12"] == "2025-02-10"


def test_each_list_follows_one_rule():
    r = build()
    assert r["lists"]["all"]["laws"]["total"] == 2 and ids(r, "all", "laws") == [3, 1]  # COD + prozatímní dohoda, nejnovější první
    assert ids(r, "m12", "laws") == [3]  # hlasování 1 je starší než 12 měsíců
    assert r["lists"]["all"]["splits"]["total"] == 2 and ids(r, "all", "splits") == [2, 5]  # stejné rozdělení 2 : 1, starší první
    assert ids(r, "all", "close")[0] == 3  # rozdíl 1 hlas
    assert ids(r, "all", "against_result") == [5]  # Češi 2 : 1 pro, parlament zamítl
    assert r["lists"]["session"]["laws"]["total"] == 0 and "4" not in r["votes"]  # dílčí hlasování nikde


def test_reasons_are_sentences_from_data_and_each_list_has_its_own():
    r = build()
    reasons = {x["id"]: x["reason"] for x in r["lists"]["all"]["close"]["items"]}
    assert reasons[3] == "Výsledek 201 : 200, rozdíl 1 hlas"
    assert r["lists"]["all"]["against_result"]["items"][0]["reason"] == "Češi 2 pro : 1 proti, parlament ale text zamítl"
    assert r["lists"]["all"]["splits"]["items"][0]["reason"].startswith("Češi se rozdělili 2 : 1")
    assert r["lists"]["all"]["laws"]["items"][0]["reason"] == "Závěrečné hlasování v legislativní proceduře MOCK/3"


def test_no_manual_input_or_media():
    r = build()
    assert "ep_highlights" not in r["lists"]["all"] and not any("press" in v for v in r["votes"].values())
