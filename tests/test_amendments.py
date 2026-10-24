import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import amendments as am  # noqa: E402

HEAD = (
    "<Commission>{AGRI}Committee on Agriculture and Rural Development</Commission>"
    "<RefProc>2025/0237</RefProc><RefTypeProc>(COD)</RefTypeProc>"
    "<Date>{22/07/2026}22.7.2026</Date><TypeAM>AMENDMENTS</TypeAM><RangeAM>{range}</RangeAM>"
)


def docx(paragraphs: list[str]) -> bytes:
    """Minimální DOCX se značkami šablony EP jako textem (stejně jako v registru EP: značky jsou v odstavcích jako text)."""
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    body = "".join(f"<w:p><w:r><w:t>{esc(p)}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def amend(num: int, members: str, behalf: str | None = None, suffix: str = "") -> list[str]:
    by = (
        [f"<RepeatBlock-By><Members>{members}</Members>"]
        + ([f"<AuNomDe>{{X}}{behalf}</AuNomDe>"] if behalf else [])
        + ["</RepeatBlock-By>"]
    )
    return [f"<Amend{suffix}>Amendment<NumAm{suffix}>{num}</NumAm{suffix}>", *by, "<Article>Recital 1</Article>", "MOCK text PN"]


def text(paragraphs: list[str]) -> str:
    return am.docx_text(docx(paragraphs))


def test_parse_committee_docx_counts_authors_sole_and_on_behalf():
    t = text(
        [HEAD.replace("{range}", "10 - 12"), "<RepeatBlock-Amend>"]
        + amend(10, "MOCK Jana Nováková")
        + amend(11, "MOCK Jana Nováková, MOCK Petr Dvořák")
        + amend(12, "MOCK Petr Dvořák", behalf="on behalf of the MOCK Group")
    )
    d = am.parse_committee_docx(t, "AGRI-AM-000001")
    assert d["kind"] == "amendments" and d["n"] == 3
    assert d["date"] == "2026-07-22" and d["committees"] == ["AGRI"] and d["procedure"] == "2025/0237(COD)"
    assert d["authors"] == {"MOCK Jana Nováková": [2, 1, 0], "MOCK Petr Dvořák": [2, 1, 1]}


def test_parse_two_column_template_a_b():
    t = text(
        [HEAD.replace("{range}", "1 - 2"), "<RepeatBlock-AmendA>"]
        + amend(1, "MOCK Jana Nováková", suffix="A")
        + ["<RepeatBlock-AmendB>"]
        + amend(2, "MOCK Jana Nováková", suffix="B")
    )
    assert am.parse_committee_docx(t)["authors"] == {"MOCK Jana Nováková": [2, 2, 0]}


def test_range_mismatch_is_format_error():
    t = text([HEAD.replace("{range}", "1 - 5"), "<RepeatBlock-Amend>"] + amend(1, "MOCK Jana Nováková"))
    with pytest.raises(am.FormatError, match="RangeAM"):
        am.parse_committee_docx(t, "X")


def test_single_amendment_without_range_and_missing_date():
    single = HEAD.replace("<RangeAM>{range}</RangeAM>", "").replace("AMENDMENTS", "AMENDMENT")
    assert am.parse_committee_docx(text([single, "<RepeatBlock-Amend>"] + amend(1, "MOCK Jana Nováková")))["n"] == 1
    with pytest.raises(am.FormatError, match="Date"):
        am.parse_committee_docx(text(["<RangeAM>1 - 1</RangeAM>", "<RepeatBlock-Amend>"] + amend(1, "MOCK")))
    with pytest.raises(am.FormatError, match="RepeatBlock"):
        am.parse_committee_docx(text([HEAD.replace("{range}", "1 - 1"), "MOCK bez bloků"]))


def test_date_with_single_digit_day():
    head = HEAD.replace("{22/07/2026}22.7.2026", "{2/02/2024}2.2.2024").replace("{range}", "1 - 1")
    assert am.parse_committee_docx(text([head, "<RepeatBlock-Amend>"] + amend(1, "MOCK Jana Nováková")))["date"] == "2024-02-02"


def test_compromise_amendments_have_no_authors():
    t = text(
        [
            HEAD.replace("{range}", "1 - 3").replace("AMENDMENTS", "COMPROMISE AMENDMENTS"),
            "<RepeatBlock-AmCompr>",
            "<SupportedBy>MOCK</SupportedBy>",
        ]
    )
    d = am.parse_committee_docx(t)
    assert d["kind"] == "compromise" and d["authors"] == {} and d["n"] is None


@pytest.mark.parametrize(
    "title, expected",
    [
        (
            "A10-0259/1 - Pozměňovací návrh 1 - MOCK Jana Nováková, MOCK Petr Dvořák - Zpráva A10-0259/2026 - MOCK",
            ("members", ["MOCK Jana Nováková", "MOCK Petr Dvořák"], None),
        ),
        (
            "A10-0031/2 - Pozměňovací návrh 2 - MOCK Jana Nováková - za skupinu The Left - Zpráva A10-0031/2024 - MOCK",
            ("group", ["MOCK Jana Nováková"], "The Left"),
        ),
        (
            "A10-0076/1 - Pozměňovací návrh 1 - MOCK Jana Nováková - Výbor pro zemědělství a rozvoj venkova - Zpráva A10-0076/2025",
            ("committee", ["MOCK Jana Nováková"], None),
        ),
        ("Pozměňovací návrh 001-005 - MOCK Zpravodaj - Zpráva A10-0276/2026 - MOCK", ("committee", [], None)),
        ("A10-0213/4 - Pozměňovacích návrh 4 - MOCK Jana Nováková - Zpráva A10-0213/2025", ("members", ["MOCK Jana Nováková"], None)),
        (
            "A10-0063/34/rev - Pozměňovací návrh 34/rev - MOCK Jana Nováková - za skupinu PfE - Zpráva A10-0063/2025",
            ("group", ["MOCK Jana Nováková"], "PfE"),
        ),
        ("Návrh usnesení MOCK", ("unknown", [], None)),
    ],
)
def test_classify_plenary(title, expected):
    assert am.classify_plenary(title) == expected


MEPS = [
    {"id": 1, "given_name": "MOCK Jana", "family_name": "Nováková", "mandates": [{"start": "2024-07-16", "end": None}]},
    {"id": 2, "given_name": "MOCK Petr", "family_name": "Dvořák", "mandates": [{"start": "2024-07-16", "end": "2025-06-30"}]},
]


def test_summarize_counts_only_in_mandate_and_matches_without_diacritics():
    state = {
        "committee": {
            "AGRI-AM-000001": {
                "kind": "amendments",
                "date": "2025-03-01",
                "committees": ["AGRI"],
                "procedure": "P1",
                "n": 3,
                "authors": {"MOCK JANA NOVAKOVA": [2, 1, 0], "MOCK Petr Dvořák": [1, 0, 1]},
            },
            "AGRI-AM-000002": {
                "kind": "amendments",
                "date": "2026-01-10",
                "committees": ["AGRI"],
                "procedure": "P1",
                "n": 1,
                "authors": {"MOCK Jana Nováková": [1, 1, 0], "MOCK Petr Dvořák": [1, 1, 0]},
            },
            "DEVE-AM-000003": {
                "kind": "compromise",
                "date": "2026-02-01",
                "committees": ["DEVE"],
                "procedure": "P2",
                "n": None,
                "authors": {},
            },
            "ENVI-AM-000004": {"kind": "missing"},
        },
        "plenary": {
            "A-10-2025-0001": {
                "amendments": [
                    {
                        "id": "A-10-2025-0001-AM-001-003",
                        "date": "2025-05-01",
                        "n": 3,
                        "kind": "members",
                        "people": ["MOCK Jana Nováková", "MOCK Petr Dvořák"],
                    },
                    {"id": "A-10-2025-0001-AM-004-004", "date": "2025-05-01", "n": 1, "kind": "group", "group": "PfE"},
                ]
            }
        },
    }
    out = am.summarize(state, MEPS)
    jana, petr = out["meps"]["1"], out["meps"]["2"]
    assert jana["committee"] | {"recent": None} == {"total": 3, "sole": 2, "on_behalf": 0, "dossiers": 1, "docs": 2, "recent": None}
    assert [r["doc"] for r in jana["committee"]["recent"]] == ["AGRI-AM-000002", "AGRI-AM-000001"]  # nejnovější první
    assert jana["committee"]["recent"][0]["url"].endswith("AGRI-AM-000002_en.pdf")
    assert petr["committee"]["total"] == 1 and petr["committee"]["on_behalf"] == 1  # dokument z 2026 je po konci mandátu
    assert jana["plenary"] == {"cosigned": 3} and petr["plenary"] == {"cosigned": 3}
    assert out["coverage"] == {
        "committee_to": "2026-02-01",
        "plenary_to": "2025-05-01",
        "committee_docs": 2,
        "committee_compromise": 1,
        "committee_pending": 1,
    }


def test_listing_resumes_after_budget(tmp_path):
    """Výpis dokumentů po 10: když vyprší čas, rozpracovaný rok zůstane ve stavu a příští běh naváže bez ztráty ID."""
    import datetime as dt

    import fetch_amendments as fa

    ids = [f"AGRI-AM-{i:06d}" for i in range(23)]

    class Client:
        calls = 0

        def get(self, path, params):
            Client.calls += 1
            off, lim = params["offset"], params["limit"]
            return {"data": [{"identifier": i} for i in ids[off : off + lim]] if params["year"] == 2026 else []}

    state = {"years_complete": [2024, 2025]}
    f = fa.Fetcher(Client(), state, tmp_path / "state.json", None, None, log=lambda m: None)
    budget = iter([False, False, True])  # třetí stránka už nestihne
    f.check_budget = lambda: (_ for _ in ()).throw(fa.Budget()) if next(budget) else None
    with pytest.raises(fa.Budget):
        f.listing(dt.date(2026, 10, 24))
    assert state["listing"]["2026"]["offset"] == 20 and len(state["listing"]["2026"]["ids"]) == 20
    f.check_budget = lambda: None
    assert f.listing(dt.date(2026, 10, 24)) == ids
    assert "2026" not in state["listing"] and state["years_complete"] == [2024, 2025]  # letošní rok se vypisuje znovu
