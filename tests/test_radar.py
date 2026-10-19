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
    tl = rd.timeline(
        ev(
            ("2024-02-08", "REFERRAL"),
            ("2025-06-24", "COMMITTEE_ADOPTING_REPORT"),
            ("2025-07-09", "PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS"),
            ("2025-10-15", "INTERINSTITUTIONAL_NEGOTIATION"),
        ),
        "COD",
    )
    assert tl["reached"] == "trilogue"
    assert [(s["label"], s["date"]) for s in tl["steps"]] == [
        ("Přiděleno výboru", "2024-02-08"),
        ("Hlasování ve výboru", "2025-06-24"),
        ("Plénum potvrdilo mandát k jednání s Radou", "2025-07-09"),
        ("Jednání s Radou (trialog)", "2025-10-15"),
        ("Hlasování pléna", None),  # čekající kroky bez data; jednání s Radou mezi nimi není (není povinné)
        ("Podpis a vyhlášení", None),
    ]
    assert tl["last_event"] == {"date": "2025-10-15", "type": "INTERINSTITUTIONAL_NEGOTIATION", "label": "jednání s Radou (trialog)"}
    assert tl["plenary_date"] is None and tl["unmapped"] == []


# Skutečné události z EP Open Data (data/proposals.json, 18. 10. 2026), ověřené proti Legislativní observatoři EP (audit UX 2026-10-18).
EDIP = ev(
    ("2024-11-13", "REFERRAL"),
    ("2025-01-30", "COMMITTEE_TABLING_OPINION"),
    ("2025-03-13", "PLENARY_VOTE"),  # samostatné obecné hlasování, není rozhodnutí o zákoně
    ("2025-03-21", "COMMITTEE_TABLING_REPORT"),
    ("2025-04-08", "COMMITTEE_ADOPTING_OPINION"),
    ("2025-04-24", "COMMITTEE_ADOPTING_REPORT"),
    ("2025-04-30", "TABLING_PLENARY"),
    ("2025-05-07", "PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS"),
    ("2025-06-30", "INTERINSTITUTIONAL_NEGOTIATION"),
    ("2025-10-16", "INTERINSTITUTIONAL_NEGOTIATION"),
    ("2025-10-20", "COMMITTEE_APPROVE_PROVISIONAL_AGREEMENT"),
    ("2025-11-20", "TABLING_PLENARY"),
    ("2025-11-24", "TABLING_PLENARY"),
    ("2025-11-25", "PLENARY_ADOPT_POSITION"),
    ("2025-11-25", "PLENARY_DEBATE"),
    ("2025-11-25", "PLENARY_VOTE"),
    ("2025-11-25", "PLENARY_VOTE_RESULTS"),
    ("2025-12-16", "SIGNATURE"),
    ("2025-12-29", "PUBLICATION_OFFICIAL_JOURNAL"),
)
ADR = ev(
    ("2023-11-20", "REFERRAL"),
    ("2023-12-20", "COMMITTEE_TABLING_REPORT"),
    ("2024-02-22", "COMMITTEE_ADOPTING_REPORT"),
    ("2024-02-26", "TABLING_PLENARY"),
    ("2024-03-11", "PLENARY_DEBATE"),
    ("2024-03-13", "PLENARY_AMEND_PROPOSAL"),
    ("2024-03-13", "PLENARY_VOTE"),
    ("2025-02-20", "INTERINSTITUTIONAL_NEGOTIATION"),
    ("2025-06-26", "INTERINSTITUTIONAL_NEGOTIATION"),
    ("2025-09-25", "COMMITTEE_APPROVE_PROVISIONAL_AGREEMENT"),
    ("2025-11-27", "REFERRAL"),
    ("2025-12-04", "COMMITTEE_ADOPTING_REPORT"),
    ("2025-12-05", "TABLING_PLENARY"),
    ("2025-12-10", "TABLING_PLENARY"),
    ("2025-12-16", "PLENARY_APPROVE_COUNCIL_POSITION"),
    ("2025-12-16", "PLENARY_VOTE"),
    ("2025-12-16", "SIGNATURE"),
    ("2025-12-30", "PUBLICATION_OFFICIAL_JOURNAL"),
)


def steps(tl):
    return [(s["label"], s["date"], s.get("date_to")) for s in tl["steps"]]


def test_timeline_edip_matches_official_key_events():
    """2024/0061(COD): plénum hlasovalo 25. 11. 2025, ne 13. 3. 2025; výbor hlasoval 24. 4., zpráva předložena 30. 4."""
    tl = rd.timeline(EDIP, "COD")
    assert tl["reached"] == "closed" and tl["plenary_date"] == "2025-11-25"
    assert steps(tl) == [
        ("Přiděleno výboru", "2024-11-13", None),
        ("Hlasování ve výboru", "2025-04-24", None),
        ("Zpráva předložena plénu", "2025-04-30", None),
        ("Plénum potvrdilo mandát k jednání s Radou", "2025-05-07", None),
        ("Jednání s Radou (trialog)", "2025-06-30", "2025-10-16"),
        ("Výbor schválil dohodu s Radou", "2025-10-20", None),
        ("Zpráva předložena plénu", "2025-11-20", "2025-11-24"),
        ("Hlasování pléna – 1.\u00a0čtení", "2025-11-25", None),
        ("Podpis aktu", "2025-12-16", None),
        ("Vyhlášení v Úředním věstníku", "2025-12-29", None),
    ]
    assert "2025-03-13" not in {s["date"] for s in tl["steps"]}


def test_timeline_adr_distinguishes_readings_and_signature_from_publication():
    """2023/0376(COD): 1. čtení 13. 3. 2024, 2. čtení 16. 12. 2025, podpis 16. 12. 2025 a vyhlášení 30. 12. 2025 zvlášť."""
    tl = rd.timeline(ADR, "COD")
    assert tl["reached"] == "closed" and tl["plenary_date"] == "2025-12-16"
    labels = steps(tl)
    assert labels[2:4] == [("Zpráva předložena plénu", "2024-02-26", None), ("Hlasování pléna – 1.\u00a0čtení", "2024-03-13", None)]
    assert labels[-3:] == [
        ("Hlasování pléna – 2.\u00a0čtení (schválen postoj Rady)", "2025-12-16", None),
        ("Podpis aktu", "2025-12-16", None),
        ("Vyhlášení v Úředním věstníku", "2025-12-30", None),
    ]
    assert labels[1] == ("Hlasování ve výboru", "2024-02-22", None)


def test_timeline_reading_only_for_ordinary_procedure_and_refer_back_hides_same_day_amendments():
    events = ev(
        ("2026-03-11", "PLENARY_AMEND"),
        ("2026-03-11", "PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS"),
        ("2026-04-01", "PLENARY_ADOPT_POSITION"),
    )
    assert [s["label"] for s in rd.timeline(events, "COD")["steps"]] == [
        "Plénum vrátilo zprávu výboru k jednání s Radou",
        "Hlasování pléna – 1.\u00a0čtení",
        "Podpis a vyhlášení",
    ]
    assert rd.timeline(events, "CNS")["steps"][1]["label"] == "Hlasování pléna"  # konzultace čtení nemá
    alone = rd.timeline(ev(("2026-03-11", "PLENARY_AMEND")), "COD")["steps"]
    assert alone[0]["label"] == "Plénum přijalo pozměňovací návrhy"


def test_timeline_in_committee_shows_pending_steps():
    tl = rd.timeline(ev(("2026-01-10", "REFERRAL"), ("2026-02-01", "COMMITTEE_TABLING_REPORT")), "COD")
    assert tl["reached"] == "committee"
    assert steps(tl) == [
        ("Přiděleno výboru", "2026-01-10", None),
        ("Hlasování ve výboru", None, None),
        ("Hlasování pléna", None, None),
        ("Podpis a vyhlášení", None, None),
    ]


def test_every_axis_event_has_stage():
    stage_types = {t for _, _, types in rd.MILESTONES for t in types}
    assert set(rd.AXIS) <= stage_types
    assert not set(rd.AXIS) & rd.GENERIC_VOTE


def test_timeline_closed_and_unknown_event_type_not_guessed():
    tl = rd.timeline(
        ev(("2025-05-22", "PLENARY_ADOPT_POSITION"), ("2025-06-20", "PUBLICATION_OFFICIAL_JOURNAL"), ("2025-07-01", "MOCK_NEW_TYPE"))
    )
    assert tl["reached"] == "closed" and tl["plenary_date"] == "2025-05-22"
    assert tl["last_event"]["type"] == "PUBLICATION_OFFICIAL_JOURNAL"  # neznámý typ se nepřekládá odhadem
    assert tl["unmapped"] == ["MOCK_NEW_TYPE"]
    assert rd.timeline([])["reached"] is None and rd.timeline([])["last_event"] is None


def test_procedure_can_go_back_after_plenary_vote():
    """2023/0288(COD): plénum hlasovalo v roce 2024, pak výbor schválil dohodu s Radou: procedura je znovu rozpracovaná."""
    tl = rd.timeline(
        ev(
            ("2024-04-24", "PLENARY_AMEND_PROPOSAL"),
            ("2024-04-24", "PLENARY_VOTE"),
            ("2025-01-16", "COMMITTEE_APPROVE_PROVISIONAL_AGREEMENT"),
        )
    )
    assert tl["reached"] == "trilogue" and tl["plenary_date"] is None
    assert tl["steps"][3]["date"] is None  # krok za aktuálním je bez data


def test_generic_plenary_vote_does_not_decide_stage():
    """Hlasování o odmítnutí mandátu k jednání s Radou není hlasování o zákoně; samostatné obecné hlasování (typicky hned po
    přidělení výboru, 2025/0329(COD)) proceduru neposune mezi odhlasované."""
    tl = rd.timeline(ev(("2025-10-22", "PLENARY_REJECT_COMMITTEE_INTERINSTUTIONAL_NEGOTIATIONS"), ("2025-10-22", "PLENARY_VOTE")))
    assert tl["reached"] == "trilogue"
    tl = rd.timeline(ev(("2025-11-12", "REFERRAL"), ("2025-11-13", "PLENARY_VOTE"), ("2025-11-13", "PLENARY_VOTE_RESULTS")))
    assert tl["reached"] == "committee" and tl["plenary_date"] is None
    assert tl["last_event"]["type"] == "REFERRAL"
    assert rd.timeline(ev(("2026-09-15", "PLENARY_VOTE")))["reached"] is None


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
    rows = rd.cz_roles(
        [
            {"mep_id": 2, "role": "RAPPORTEUR_SHADOW"},
            {"mep_id": 2, "role": "RAPPORTEUR"},
            {"mep_id": 1, "role": "RAPPORTEUR_SHADOW_OPINION"},
            {"mep_id": 3, "role": "AUTHOR"},
        ],
        {1: "MOCK Jedna", 2: "MOCK Dva"},
    )
    assert [(r["mep_id"], r["role"]) for r in rows] == [(2, "rapporteur"), (1, "shadow_opinion")]


def proc(pid, events, ptype="COD", roles=(("RAPPORTEUR_SHADOW", 1),), committee="TRAN", with_events=True):
    item = {
        "id": f"proc-{pid}",
        "kind": "procedure",
        "procedure": pid,
        "label": f"{pid.replace('-', '/')}({ptype})",
        "process_type": ptype,
        "title": {"cs": f"MOCK {pid}", "en": None},
        "url": None,
        "committee": committee,
        "participants": [{"mep_id": m, "role": r} for r, m in roles],
    }
    if with_events:
        item["events"] = events
    return item


def test_procedures_split_into_active_and_done():
    proposals = {
        "items": [
            proc("2025-0001", ev(("2025-02-01", "REFERRAL"))),
            proc("2025-0002", ev(("2025-02-01", "REFERRAL"), ("2026-01-10", "INTERINSTITUTIONAL_NEGOTIATION"))),
            proc("2025-0003", ev(("2026-09-15", "PLENARY_ADOPT_POSITION"), ("2026-09-15", "PLENARY_VOTE"))),  # odhlasováno
            proc("2023-0004", ev(("2024-01-10", "PLENARY_ADOPT_POSITION"), ("2024-02-01", "SIGNATURE"))),  # dávno uzavřeno
            proc("2025-0005", ev(("2025-02-01", "REFERRAL")), ptype="INI"),  # nelegislativní
            proc("2025-0006", ev(("2025-02-01", "REFERRAL")), roles=(("AUTHOR", 1),)),  # bez české role
            proc("2025-0007", [], with_events=False),  # ještě nestaženo
        ]
    }
    votes = rd.vote_links(
        [
            {"id": 98, "date": "2026-09-15", "vote_kind": "amendment", "result": "ADOPTED", "procedure": {"reference": "2025/0003(COD)"}},
            {"id": 99, "date": "2026-09-15", "vote_kind": "final", "result": "ADOPTED", "procedure": {"reference": "2025/0003(COD)"}},
            {"id": 50, "date": "2025-01-10", "vote_kind": "final", "result": "REJECTED", "procedure": {"reference": "2025/0003(COD)"}},
        ]
    )
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
    agenda = {
        "fetched": "2026-10-16",
        "docs": {"A-10-2026-0213": {"procedure": "2025-2121", "committee": "CONT"}},
        "next": {
            "from": "2026-10-19",
            "to": "2026-10-22",
            "days": ["2026-10-19"],
            "items": [
                {
                    "id": "MOCK-1",
                    "date": "2026-10-20",
                    "order": 1,
                    "title_cs": "MOCK DPH",
                    "title_en": None,
                    "docs": ["A-10-2026-0213"],
                    "legislative": False,
                    "stage": "RDG1",
                },
                {
                    "id": "MOCK-2",
                    "date": "2026-10-21",
                    "order": 2,
                    "title_cs": "MOCK bez dokumentu",
                    "title_en": None,
                    "docs": [],
                    "legislative": False,
                    "stage": None,
                },
            ],
        },
    }
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


def test_non_legislative_procedure_does_not_wait_for_signature():
    tl = rd.timeline(ev(("2026-01-10", "REFERRAL"), ("2026-09-01", "COMMITTEE_ADOPTING_REPORT")), "INI")
    assert [s["label"] for s in tl["steps"] if not s["date"]] == ["Hlasování pléna"]
