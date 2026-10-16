import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import agenda as ag  # noqa: E402
import fetch_agenda as fa  # noqa: E402
from fetch_meps import FormatError  # noqa: E402

VOTE = fa.VOTE_TYPE


class FakeClient:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, path, params=None):
        self.calls.append((path, params))
        key = (path, (params or {}).get("year"))
        if key not in self.routes:
            raise AssertionError(f"neočekávaný dotaz {key}")
        return self.routes[key]


def act(i, day, typ=VOTE, docs=(), order=None, cs="MOCK_bod"):
    return {"activity_id": f"MOCK-{i}", "activity_date": f"{day}T09:00:00", "had_activity_type": typ,
            "activity_label": {"cs": cs, "en": "MOCK item"}, "activity_order": order,
            "based_on_a_realization_of": [f"eli/dl/doc/{d}" for d in docs]}


def test_doc_key_both_formats():
    assert ag.doc_key("A10-0120/2025") == "A-10-2025-0120"
    assert ag.doc_key("A-10-2025-0120") == "A-10-2025-0120"
    assert ag.doc_key("2023/0436(COD)") is None
    assert ag.doc_key(None) is None


def test_group_and_next_session():
    days = ["2026-10-19", "2026-10-20", "2026-10-22", "2026-11-11", "2026-11-12"]
    assert fa.group_sessions(days) == [["2026-10-19", "2026-10-20", "2026-10-22"], ["2026-11-11", "2026-11-12"]]
    assert fa.next_session(days, "2026-10-16") == ["2026-10-19", "2026-10-20", "2026-10-22"]
    assert fa.next_session(days, "2026-10-21") == ["2026-10-19", "2026-10-20", "2026-10-22"]  # probíhá
    assert fa.next_session(days, "2026-10-23") == ["2026-11-11", "2026-11-12"]
    assert fa.next_session(days, "2026-12-01") is None


def test_vote_items_only_votes_with_docs_and_order():
    payload = {"data": [act(1, "2026-10-20", docs=["A-10-2026-0213", "C-10-2026-0001"], order="12"),
                        act(2, "2026-10-20", typ="def/ep-activities/PLENARY_DEBATE"),
                        act(3, "2026-10-20", order=3)]}
    items = fa.vote_items(payload, "2026-10-20")
    assert [i["id"] for i in items] == ["MOCK-3", "MOCK-1"]
    assert items[1]["docs"] == ["A-10-2026-0213", "C-10-2026-0001"] and items[1]["legislative"]
    assert items[0]["docs"] == [] and not items[0]["legislative"]


def test_vote_items_format_error():
    with pytest.raises(FormatError):
        fa.vote_items({"items": []}, "2026-10-20")
    with pytest.raises(FormatError):
        fa.vote_items({"data": [{"activity_id": "x"}]}, "2026-10-20")


def test_build_and_write_if_changed(tmp_path):
    routes = {("meetings", 2026): {"data": [{"activity_id": "MTG-PL-2026-10-19"}, {"activity_id": "MTG-PL-2026-10-20"},
                                             {"activity_id": "MTG-COMMITTEE-x"}]},
              ("meetings/MTG-PL-2026-10-19/foreseen-activities", None): {"data": [act(1, "2026-10-19", docs=["A-10-2026-0001"])]},
              ("meetings/MTG-PL-2026-10-20/foreseen-activities", None): {"data": []}}
    doc = fa.build(FakeClient(routes), "2026-10-16")
    assert doc["sittings"] == ["2026-10-19", "2026-10-20"]
    assert doc["next"]["from"] == "2026-10-19" and len(doc["next"]["items"]) == 1
    out = tmp_path / "agenda.json"
    assert fa.write_if_changed(out, doc, "2026-10-16")
    assert not fa.write_if_changed(out, doc, "2026-10-17")  # stejný obsah: datum se nepřepíše
    assert json.loads(out.read_text())["fetched"] == "2026-10-16"


def test_build_no_sittings_is_error():
    with pytest.raises(FormatError):
        fa.build(FakeClient({("meetings", 2026): {"data": []}}), "2026-10-16")


OWN = {"meps": {
    "1": {"items": [{"type": "report", "id": "A-10-2026-0213", "role": "RAPPORTEUR"},
                    {"type": "motion", "id": "B-10-2026-0001"}]},
    "2": {"items": [{"type": "shadow_report", "id": "proc-x", "report": "A10-0213/2026"},
                    {"type": "report", "id": "A-10-2026-0300", "role": "RAPPORTEUR_CO"}]},
}}


def test_cz_roles_by_doc_joins_both_formats():
    roles = ag.cz_roles_by_doc(OWN)
    assert roles["A-10-2026-0213"] == [{"mep_id": 1, "role": "rapporteur"}, {"mep_id": 2, "role": "shadow"}]
    assert roles["A-10-2026-0300"] == [{"mep_id": 2, "role": "co"}]
    assert "B-10-2026-0001" not in roles


def item(i, docs, legislative=False, order=None, day="2026-10-20"):
    return {"id": f"MOCK-{i}", "date": day, "order": order, "title_cs": "MOCK", "title_en": None,
            "docs": docs, "legislative": legislative}


def test_agenda_view_picks_trace_then_legislative_then_order():
    agenda = {"fetched": "2026-10-16", "source": {"name": "MOCK"},
              "next": {"from": "2026-10-19", "to": "2026-10-22", "days": ["2026-10-19"], "items": [
                  item(1, ["B-10-2026-0001"], order=1), item(2, ["C-10-2026-0002"], legislative=True, order=5),
                  item(3, [], order=0), item(4, ["A-10-2026-0213"], order=9), item(5, ["A-10-2026-0400"], order=2)]}}
    view = ag.agenda_view(agenda, OWN, {1: "MOCK Jedna", 2: "MOCK Dva"})
    assert view["picks"] == ["MOCK-4", "MOCK-2", "MOCK-1"]
    assert view["votes"] == 5
    trace = next(x for x in view["items"] if x["id"] == "MOCK-4")["cz"]
    assert [r["name"] for r in trace] == ["MOCK Jedna", "MOCK Dva"]
    assert all(not x["cz"] for x in view["items"] if x["id"] != "MOCK-4")  # štítek jen při existujícím záznamu


def test_agenda_view_without_program():
    assert ag.agenda_view(None, OWN, {}) is None
    assert ag.agenda_view({"next": None}, OWN, {}) is None
