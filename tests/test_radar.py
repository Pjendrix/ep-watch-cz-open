"""Radar „Co se chystá“ (scripts/radar.py): kroky procedury z událostí, výběr rozpracovaných a odhlasovaných, česká stopa."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import categories  # noqa: E402
import radar as rd  # noqa: E402

TODAY = "2026-10-16"


def ev(*pairs):
    return [{"date": d, "type": t} for d, t in pairs]


def test_timeline_steps_from_events_not_current_stage():
    tl = rd.timeline(ev(("2024-02-08", "REFERRAL"), ("2025-06-24", "COMMITTEE_ADOPTING_REPORT"),
                        ("2025-07-09", "PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS"),
                        ("2025-10-15", "INTERINSTITUTIONAL_NEGOTIATION")))
    assert tl["reached"] == "trilogue"
    assert [s["date"] for s in tl["steps"]] == ["2024-02-08", "2025-06-24", "2025-07-09", None, None]
    assert tl["last_event"] == {"date": "2025-10-15", "type": "INTERINSTITUTIONAL_NEGOTIATION", "label": "jednání s Radou (trialog)"}
    assert tl["plenary_date"] is None and tl["unmapped"] == []


def test_timeline_closed_and_unknown_event_type_not_guessed():
    tl = rd.timeline(ev(("2025-05-22", "PLENARY_ADOPT_POSITION"), ("2025-06-20", "PUBLICATION_OFFICIAL_JOURNAL"),
                        ("2025-07-01", "MOCK_NEW_TYPE")))
    assert tl["reached"] == "closed" and tl["plenary_date"] == "2025-05-22"
    assert tl["last_event"]["type"] == "PUBLICATION_OFFICIAL_JOURNAL"  # neznámý typ se nepřekládá odhadem
    assert tl["unmapped"] == ["MOCK_NEW_TYPE"]
    assert rd.timeline([])["reached"] is None and rd.timeline([])["last_event"] is None


def test_procedure_can_go_back_after_plenary_vote():
    """2023/0288(COD): plénum hlasovalo v roce 2024, pak výbor schválil dohodu s Radou: procedura je znovu rozpracovaná."""
    tl = rd.timeline(ev(("2024-04-24", "PLENARY_AMEND_PROPOSAL"), ("2024-04-24", "PLENARY_VOTE"),
                        ("2025-01-16", "COMMITTEE_APPROVE_PROVISIONAL_AGREEMENT")))
    assert tl["reached"] == "trilogue" and tl["plenary_date"] is None
    assert tl["steps"][3]["date"] is None  # krok za aktuálním je bez data


def test_generic_plenary_vote_does_not_beat_specific_event_same_day():
    """Hlasování o odmítnutí mandátu k jednání s Radou není hlasování o zákoně."""
    tl = rd.timeline(ev(("2025-10-22", "PLENARY_REJECT_COMMITTEE_INTERINSTUTIONAL_NEGOTIATIONS"), ("2025-10-22", "PLENARY_VOTE")))
    assert tl["reached"] == "trilogue"
    assert rd.timeline(ev(("2026-09-15", "PLENARY_VOTE")))["reached"] == "plenary"


def test_every_event_type_in_milestones_has_czech_label():
    for _, _, types in rd.MILESTONES:
        assert types <= set(rd.EVENT_CS)


def test_committee_categories_exist_on_web():
    keys = {k for k, _, _ in categories.CATEGORIES}
    assert all(cat in keys for _, cat in rd.COMMITTEES.values() if cat)
    assert rd.committee_info("ENVI") == {"code": "ENVI", "name": "Životní prostředí, klima a bezpečnost potravin", "category": "env"}
    assert rd.committee_info("MOCK") == {"code": "MOCK", "name": None, "category": None}
    assert rd.committee_info(None) is None


def test_process_type_and_roles():
    assert rd.process_type("2023/0436(COD)") == "COD" and rd.process_type(None) is None and rd.process_type("x") is None
    rows = rd.cz_roles([{"mep_id": 2, "role": "RAPPORTEUR_SHADOW"}, {"mep_id": 2, "role": "RAPPORTEUR"},
                        {"mep_id": 1, "role": "RAPPORTEUR_SHADOW_OPINION"}, {"mep_id": 3, "role": "AUTHOR"}],
                       {1: "MOCK Jedna", 2: "MOCK Dva"})
    assert [(r["mep_id"], r["role"]) for r in rows] == [(2, "rapporteur"), (1, "shadow_opinion")]


def proc(pid, events, ptype="COD", roles=(("RAPPORTEUR_SHADOW", 1),), committee="TRAN", with_events=True):
    item = {"id": f"proc-{pid}", "kind": "procedure", "procedure": pid, "label": f"{pid.replace('-', '/')}({ptype})",
            "process_type": ptype, "title": {"cs": f"MOCK {pid}", "en": None}, "url": None, "committee": committee,
            "participants": [{"mep_id": m, "role": r} for r, m in roles]}
    if with_events:
        item["events"] = events
    return item


def test_procedures_split_into_active_and_done():
    proposals = {"items": [
        proc("2025-0001", ev(("2025-02-01", "REFERRAL"))),
        proc("2025-0002", ev(("2025-02-01", "REFERRAL"), ("2026-01-10", "INTERINSTITUTIONAL_NEGOTIATION"))),
        proc("2025-0003", ev(("2026-09-15", "PLENARY_VOTE"))),                          # odhlasováno
        proc("2023-0004", ev(("2024-01-10", "PLENARY_VOTE"), ("2024-02-01", "SIGNATURE"))),  # dávno uzavřeno
        proc("2025-0005", ev(("2025-02-01", "REFERRAL")), ptype="INI"),                 # nelegislativní
        proc("2025-0006", ev(("2025-02-01", "REFERRAL")), roles=(("AUTHOR", 1),)),       # bez české role
        proc("2025-0007", [], with_events=False),                                       # ještě nestaženo
    ]}
    votes = rd.vote_links([
        {"id": 98, "date": "2026-09-15", "vote_kind": "amendment", "result": "ADOPTED", "procedure": {"reference": "2025/0003(COD)"}},
        {"id": 99, "date": "2026-09-15", "vote_kind": "final", "result": "ADOPTED", "procedure": {"reference": "2025/0003(COD)"}},
        {"id": 50, "date": "2025-01-10", "vote_kind": "final", "result": "REJECTED", "procedure": {"reference": "2025/0003(COD)"}}])
    session = {"items": [{"date": "2026-10-20", "procedure": {"id": "2025-0001"}}]}
    active, done, missing, unmapped = rd.procedures_view(proposals, votes, {1: "MOCK"}, session, TODAY)
    assert [r["procedure"] for r in active] == ["2025-0001", "2025-0002"]  # na programu první, pak blíž hlasování
    assert active[1]["next_vote"] is None
    active, *_ = rd.procedures_view(proposals, votes, {1: "MOCK"}, None, TODAY)
    assert [r["procedure"] for r in active] == ["2025-0002", "2025-0001"]
    assert [r["procedure"] for r in done] == ["2025-0003"]
    assert done[0]["vote"] == {"vote_id": 99, "vote_date": "2026-09-15", "status": "ADOPTED"}
    assert missing == 1 and unmapped == []
    assert active[0]["committee"]["category"] == "tra" and active[0]["cz"][0]["role_cs"] == "stínový/á zpravodaj/ka"


def test_session_view_links_report_to_procedure_and_trace():
    agenda = {"fetched": "2026-10-16", "docs": {"A-10-2026-0213": {"procedure": "2025-2121", "committee": "CONT"}},
              "next": {"from": "2026-10-19", "to": "2026-10-22", "days": ["2026-10-19"], "items": [
                  {"id": "MOCK-1", "date": "2026-10-20", "order": 1, "title_cs": "MOCK DPH", "title_en": None,
                   "docs": ["A-10-2026-0213"], "legislative": False, "stage": "RDG1"},
                  {"id": "MOCK-2", "date": "2026-10-21", "order": 2, "title_cs": "MOCK bez dokumentu", "title_en": None,
                   "docs": [], "legislative": False, "stage": None}]}}
    own = {"meps": {"7": {"items": [{"type": "report", "id": "A-10-2026-0213", "role": "RAPPORTEUR"}]}}}
    s = rd.session_view(agenda, own, {7: "MOCK Sedm"}, {"2025-2121": "2025/2121(INI)"})
    a, b = s["items"]
    assert a["procedure"]["label"] == "2025/2121(INI)" and a["procedure"]["type"] == "INI"
    assert a["committee"]["category"] == "fin" and a["stage_cs"] == "první čtení"
    assert a["cz"] == [{"mep_id": 7, "name": "MOCK Sedm", "role": "rapporteur", "role_cs": "zpravodaj/ka"}]
    assert b["procedure"] is None and b["committee"] is None and b["cz"] == [] and b["stage_cs"] is None
    assert rd.session_view(None, own, {}, {}) is None


def test_build_on_real_data_has_valid_shape():
    root = Path(__file__).resolve().parent.parent / "data"
    if not (root / "agenda.json").exists():
        return
    r = rd.build(root, TODAY)
    json.dumps(r)
    for row in r["active"] + r["done"]:
        assert row["cz"] and row["type"] in rd.LEGISLATIVE
