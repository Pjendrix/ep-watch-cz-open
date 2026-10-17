import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_meps as fm  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "ep"


@pytest.fixture
def person():
    return json.loads((FIXTURES / "mep_MOCK_1.json").read_text(encoding="utf-8"))["data"][0]


@pytest.fixture
def get_body():
    bodies = json.loads((FIXTURES / "bodies_MOCK.json").read_text(encoding="utf-8"))
    return lambda org: bodies[org.removeprefix("org/")]


def test_parse_mep_term10_only(person, get_body):
    m = fm.parse_mep(person, get_body)
    assert m["id"] == 1
    assert m["name"] == "MOCK Jana NOVÁKOVÁ"
    assert m["gender"] == "FEMALE"
    assert m["photo_url"] == "https://www.europarl.europa.eu/mepphoto/1.jpg"
    assert m["photo_credit"] == "© European Union – Source: EP"
    # mandát z 9. období se nebere
    assert m["mandates"] == [{"start": "2024-07-16", "end": "2025-10-03", "mandate_id": "900"}]
    # historie frakcí v 10. období, seřazená; stará frakce z 9. období vynechaná
    assert [(g["code"], g["start"], g["end"]) for g in m["groups"]] == [
        ("PFE", "2024-07-16", "2025-02-03"),
        ("NI", "2025-02-04", "2025-10-03"),
    ]
    assert m["groups"][0]["name_cs"] == "MOCK Patrioti"
    assert m["parties"] == [
        {"org_id": "20", "short_label": "MOCK_P", "name": "MOCK strana", "role": "MEMBER", "start": "2024-07-16", "end": None}
    ]
    # výbory ano, delegace ne
    assert [(c["code"], c["type"], c["role"]) for c in m["committees"]] == [
        ("ENVI", "STANDING", "MEMBER_SUBSTITUTE"),
    ]


def test_missing_photo_is_null(person, get_body):
    del person["img"]
    m = fm.parse_mep(person, get_body)
    assert m["photo_url"] is None and m["photo_credit"] is None


def test_missing_gender_is_null(person, get_body):
    del person["hasGender"]
    assert fm.parse_mep(person, get_body)["gender"] is None


def test_missing_party_stays_empty(person, get_body):
    person["hasMembership"] = [x for x in person["hasMembership"] if x.get("membershipClassification") != fm.CLS_PARTY]
    assert fm.parse_mep(person, get_body)["parties"] == []


@pytest.mark.parametrize(
    "mutate,msg",
    [
        (lambda p: p.pop("hasMembership"), "chybí pole"),
        (lambda p: p.pop("identifier"), "chybí pole"),
        (lambda p: p["hasMembership"][1].pop("memberDuring"), "chybí pole"),
        (lambda p: p["hasMembership"][1]["memberDuring"].pop("startDate"), "chybí pole"),
        (lambda p: p["hasMembership"].pop(1), "nemá mandát"),
        (lambda p: p["hasMembership"][1].update(represents=["x/SVK"]), "nereprezentuje ČR"),
    ],
)
def test_format_errors(person, get_body, mutate, msg):
    p = copy.deepcopy(person)
    mutate(p)
    with pytest.raises(fm.FormatError, match=msg):
        fm.parse_mep(p, get_body)


def test_first_item_validates():
    assert fm.first_item({"data": [{"a": 1}]}, "x") == {"a": 1}
    with pytest.raises(fm.FormatError):
        fm.first_item({"data": []}, "x")
    with pytest.raises(fm.FormatError):
        fm.first_item({"items": []}, "x")


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        path = url.removeprefix(fm.API + "/")
        if path == "meps":
            items = self.routes["meps"]
            off, lim = params["offset"], params["limit"]
            return FakeResponse({"data": items[off : off + lim]})
        return FakeResponse(self.routes[path])


def test_fetch_paginates_and_caches_bodies(tmp_path, person):
    bodies = json.loads((FIXTURES / "bodies_MOCK.json").read_text(encoding="utf-8"))
    p2 = copy.deepcopy(person)
    p2["identifier"], p2["label"] = "2", "MOCK Petr DVOŘÁK"
    listed = [{"identifier": "1", "label": "MOCK Jana NOVÁKOVÁ"}, {"identifier": "2", "label": "MOCK Petr DVOŘÁK"}]
    routes = {"meps": listed, "meps/1": {"data": [person]}, "meps/2": {"data": [p2]}}
    routes.update({f"corporate-bodies/{k}": {"data": [v]} for k, v in bodies.items()})
    session = FakeSession(routes)
    client = fm.EPClient(cache_dir=tmp_path / "cache", session=session, min_interval=0)

    data = fm.EPClient.list_meps(client, page=1)
    assert [x["identifier"] for x in data] == ["1", "2"]

    out = fm.fetch(client)
    assert [m["id"] for m in out["meps"]] == [1, 2]
    assert out["source"]["license"] == "CC BY 4.0"
    body_calls = [u for u, _ in session.calls if "corporate-bodies" in u]
    assert len(body_calls) == len(set(body_calls))  # každá organizace jen jednou
    assert (tmp_path / "cache" / "11.json").exists()
    assert all(p["format"] == "application/ld+json" for _, p in session.calls)


def test_client_retries_on_429(monkeypatch):
    responses = [FakeResponse({}, 429), FakeResponse({"data": [{"identifier": "1"}]})]

    class S:
        def get(self, *a, **kw):
            return responses.pop(0)

    monkeypatch.setattr(fm.time, "sleep", lambda s: None)
    client = fm.EPClient(session=S(), min_interval=0)
    assert client.get("meps/1") == {"data": [{"identifier": "1"}]}


def test_client_honours_retry_after(monkeypatch):
    class R429(FakeResponse):
        def __init__(self):
            super().__init__({}, 429)
            self.headers = {"Retry-After": "7"}

    responses = [R429(), FakeResponse({"data": []})]
    slept = []

    class S:
        def get(self, *a, **kw):
            return responses.pop(0)

    monkeypatch.setattr(fm.time, "sleep", lambda s: slept.append(s))
    assert fm.EPClient(session=S(), min_interval=0).get("meps") == {"data": []}
    assert 7.0 in slept


def test_client_retries_on_timeout_and_reports_last_error(monkeypatch):
    """Timeout nebo výpadek spojení se zkouší znovu; když se nepovede ani na osmý pokus, chyba to řekne."""
    import requests

    calls = []

    class S:
        def __init__(self, fail):
            self.fail = fail

        def get(self, *a, **kw):
            calls.append(1)
            if len(calls) <= self.fail:
                raise requests.Timeout("MOCK")
            return FakeResponse({"data": []})

    monkeypatch.setattr(fm.time, "sleep", lambda s: None)
    assert fm.EPClient(session=S(2), min_interval=0).get("meps") == {"data": []}
    calls.clear()
    with pytest.raises(RuntimeError, match="Timeout"):
        fm.EPClient(session=S(99), min_interval=0).get("meps")
