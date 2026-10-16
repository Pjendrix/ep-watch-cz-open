import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_proposals as fp  # noqa: E402

CZ = {1, 2}


def part(pid, role, group=None, in_name_of=None, term="org/ep-10"):
    p = {"had_participant_person": [f"person/{pid}"], "participation_role": f"def/ep-roles/{role}",
         "parliamentary_term": term}
    if group:
        p["politicalGroup"] = f"org/{group}"
    if in_name_of:
        p["participation_in_name_of"] = f"org/{in_name_of}"
    return p


def test_report_with_cz_rapporteur():
    doc = {"identifier": "A-10-2025-0142", "label": "A10-0142/2025", "document_date": "2025-07-16",
           "work_type": "def/ep-document-types/REPORT_PLENARY",
           "title_dcterms": {"cs": "MOCK zpráva", "en": "MOCK report", "de": "x"},
           "inverse_created_a_realization_of": "eli/dl/proc/2025-0001",  # jediná hodnota bez seznamu
           "workHadParticipation": [{"had_participant_organization": ["org/AFET"], "participation_role": "def/ep-roles/AUTHOR"},
                                    part(1, "RAPPORTEUR", "PFE", "AFET")]}
    meta, item = fp.parse_document(doc, CZ)
    assert meta["procedure"] == "2025-0001" and meta["kind"] == "report"
    assert item["title"] == {"cs": "MOCK zpráva", "en": "MOCK report"}
    assert item["participants"] == [{"mep_id": 1, "role": "RAPPORTEUR", "group": "PFE", "in_name_of": "AFET", "date": None}]
    assert item["url"].endswith("A-10-2025-0142_EN.html")


def test_motion_without_cz_keeps_links_only():
    doc = {"identifier": "RC-10-2025-0156", "work_type": "def/ep-document-types/RESOLUTION_MOTION_JOINT",
           "is_derivative_of": ["eli/dl/doc/B-10-2025-0163", "eli/dl/doc/B-10-2025-0156"],
           "workHadParticipation": [part(99, "AUTHOR", in_name_of="PPE")]}
    meta, item = fp.parse_document(doc, CZ)
    assert item is None
    assert meta["derived_from"] == ["B-10-2025-0163", "B-10-2025-0156"]


def test_motion_signatories_counted():
    doc = {"identifier": "B-10-2025-0001", "work_type": "def/ep-document-types/RESOLUTION_MOTION",
           "workHadParticipation": [part(1, "AUTHOR", in_name_of="PPE"), part(2, "AUTHOR", in_name_of="PPE"),
                                    part(99, "AUTHOR", in_name_of="PPE")]}
    _, item = fp.parse_document(doc, CZ)
    assert [p["mep_id"] for p in item["participants"]] == [1, 2]
    assert item["signatories_total"] == 3


def test_procedure_single_participation_object_and_term_filter():
    proc = {"process_id": "2025-0084", "label": "2025/0084(COD)", "process_type": "def/ep-procedure-types/COD",
            "process_title": {"cs": "MOCK procedura"},
            "had_participation": part(2, "RAPPORTEUR_SHADOW", "ECR")}  # jediný objekt místo seznamu
    item = fp.parse_procedure(proc, CZ)
    assert item["participants"][0]["role"] == "RAPPORTEUR_SHADOW"
    assert item["url"].endswith("reference=2025/0084(COD)")
    proc["had_participation"] = [part(2, "RAPPORTEUR_SHADOW", "ECR", term="org/ep-9")]
    assert fp.parse_procedure(proc, CZ) is None  # účast z 9. období se nepočítá


def test_procedure_unexpected_participation_raises():
    with pytest.raises(fp.FormatError, match="neočekávaná účast"):
        fp.parse_procedure({"process_id": "x", "had_participation": ["eli/dl/participation/x"]}, CZ)


def test_question_with_answer():
    q = {"identifier": "E-10-2026-000187", "document_date": "2026-01-19",
         "work_type": "def/ep-document-types/QUESTION_WRITTEN",
         "workHadParticipation": [part(1, "AUTHOR"), part(99, "AUTHOR"),
                                  {"had_participant_organization": "org/COM", "participation_role": "def/ep-roles/ADDRESSEE"}],
         "inverse_answers_to": {"document_date": "2026-03-02"}}
    item = fp.parse_question(q, CZ)
    assert item["label"] == "E-000187/2026"
    assert item["authors_total"] == 2 and item["addressee"] == ["COM"]
    assert item["answer_date"] == "2026-03-02"


class FakeClient:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, path, params=None):
        self.calls.append(path)
        if params and params.get("language") == "en":
            return {"data": [{**self.routes[path], "title_dcterms": {"en": "MOCK English title"}}]}
        if path in ("plenary-documents", "parliamentary-questions", "procedures"):
            data = self.routes[path] if params["offset"] == 0 else []
            return {"data": data}
        return {"data": [self.routes[path]]}


def make_fetcher(routes, state=None, items=None, budget=100):
    state = state or {"documents": {}, "procedures": {}, "questions": {}}
    client = FakeClient(routes)
    return fp.Fetcher(client, CZ, state, items if items is not None else {}, budget, "2026-10-14"), client


def test_documents_incremental_and_term_filter():
    routes = {
        "plenary-documents": [{"identifier": "A-9-2024-0001"}, {"identifier": "B-10-2025-0001"}, {"identifier": "B-10-2025-0002"}],
        "plenary-documents/B-10-2025-0001": {"identifier": "B-10-2025-0001", "work_type": "def/ep-document-types/RESOLUTION_MOTION",
                                             "workHadParticipation": [part(1, "AUTHOR")]},
        "plenary-documents/B-10-2025-0002": {"identifier": "B-10-2025-0002", "work_type": "def/ep-document-types/RESOLUTION_MOTION"},
    }
    f, client = make_fetcher(routes)
    f.documents([2025])
    assert set(f.state["documents"]) == {"B-10-2025-0001", "B-10-2025-0002"}  # 9. období se přeskočí
    assert list(f.items) == ["B-10-2025-0001"]
    f2, client2 = make_fetcher(routes, state=f.state, items=f.items)
    f2.documents([2025])
    assert client2.calls == ["plenary-documents"]  # už stažené se znovu nestahují


def test_budget_stops_run():
    routes = {"plenary-documents": [{"identifier": "B-10-2025-0001"}],
              "plenary-documents/B-10-2025-0001": {"identifier": "B-10-2025-0001", "work_type": "x"}}
    f, _ = make_fetcher(routes, budget=1)
    with pytest.raises(fp.Budget):
        f.documents([2025])


def test_unanswered_cz_questions_are_rechecked():
    routes = {"parliamentary-questions": [],
              "parliamentary-questions/E-10-2025-000001": {
                  "identifier": "E-10-2025-000001", "work_type": "def/ep-document-types/QUESTION_WRITTEN",
                  "workHadParticipation": [part(1, "AUTHOR")], "inverse_answers_to": [{"document_date": "2025-03-01"}]}}
    items = {"E-10-2025-000001": {"id": "E-10-2025-000001", "kind": "question_written", "answer_date": None}}
    state = {"documents": {}, "procedures": {}, "questions": {"E-10-2025-000001": {"fetched": "2025-01-01"}}}
    f, client = make_fetcher(routes, state=state, items=items)
    f.questions([2025])
    assert f.items["E-10-2025-000001"]["answer_date"] == "2025-03-01"


def test_english_title_fallback_only_when_czech_missing():
    routes = {"plenary-documents": [{"identifier": "B-10-2025-0001"}, {"identifier": "B-10-2025-0002"}],
              "plenary-documents/B-10-2025-0001": {"identifier": "B-10-2025-0001", "work_type": "def/ep-document-types/RESOLUTION_MOTION",
                                                   "title_dcterms": {"cs": "MOCK český"}, "workHadParticipation": [part(1, "AUTHOR")]},
              "plenary-documents/B-10-2025-0002": {"identifier": "B-10-2025-0002", "work_type": "def/ep-document-types/RESOLUTION_MOTION",
                                                   "workHadParticipation": [part(1, "AUTHOR")]}}
    f, client = make_fetcher(routes)
    f.documents([2025])
    assert f.items["B-10-2025-0001"]["title"] == {"cs": "MOCK český", "en": None}
    assert f.items["B-10-2025-0002"]["title"]["en"] == "MOCK English title"
    assert client.calls.count("plenary-documents/B-10-2025-0002") == 2 and client.calls.count("plenary-documents/B-10-2025-0001") == 1


def test_deadline_stops_run():
    routes = {"plenary-documents": [{"identifier": "B-10-2025-0001"}]}
    f, _ = make_fetcher(routes)
    f.deadline = 0  # už vypršel
    with pytest.raises(fp.Budget):
        f.documents([2025])


def test_voted_procedures_get_czech_title_first(tmp_path):
    """Procedury, o kterých se hlasovalo a nemají český název, se stáhnou i když jsou jinak čerstvé; název se uloží do stavu."""
    routes = {
        "procedures": [{"process_id": "2025-0001"}],
        "procedures/2025-0001": {"process_id": "2025-0001", "label": "2025/0001(COD)", "process_title": {"cs": "MOCK nový"}},
        "procedures/2023-0436": {"process_id": "2023-0436", "label": "2023/0436(COD)", "process_title": {"cs": "MOCK starší"}},
    }
    state = {"documents": {}, "questions": {}, "procedures": {
        "2025-0001": {"fetched": "2026-10-13", "label": "2025/0001(COD)", "title_cs": "MOCK nový"}}}
    fetcher, client = make_fetcher(routes, state)
    fetcher.voted = {"2023-0436", "2025-0001"}
    fetcher.procedures([2025])
    assert "procedures/2023-0436" in client.calls and "procedures/2025-0001" not in client.calls
    assert state["procedures"]["2023-0436"]["title_cs"] == "MOCK starší"


def test_voted_procedures_from_votes(tmp_path):
    import json
    votes = tmp_path / "votes"
    votes.mkdir()
    (votes / "index.json").write_text(json.dumps({"months": [{"month": "2026-10"}]}), encoding="utf-8")
    (votes / "2026-10.json").write_text(json.dumps({"votes": [
        {"procedure": {"reference": "2023/0436(COD)"}}, {"procedure": {"reference": None}}, {"procedure": {}}]}), encoding="utf-8")
    assert fp.voted_procedures(votes) == {"2023-0436"}
    assert fp.voted_procedures(tmp_path / "nic") == set()
