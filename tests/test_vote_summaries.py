import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vote_summaries as vs  # noqa: E402


def mock_vote(i=1, title="MOCK Situation in Georgia", date="2026-10-08"):
    return {
        "id": i,
        "date": date,
        "timestamp": f"{date}T12:00:00",
        "title": title,
        "title_cs": "MOCK Situace v Gruzii",
        "vote_kind": "final",
        "is_main": True,
        "result": "ADOPTED",
        "description_cs": "Návrh usnesení (celý text)",
        "procedure": {"reference": "2026/2913(RSP)", "title": title, "type": "RSP"},
        "topics": {"eurovoc": [{"code": "1", "label": "democracy"}], "oeil": [], "geo": [{"code": "GEO", "label": "Georgia"}]},
        "counts": {"for": 500, "against": 100, "abstention": 20},
    }


class Fake:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def ask(self, source):
        self.calls += 1
        return {"shrnuti": self.text}


def test_input_has_no_result_or_counts():
    src = vs.vote_input(mock_vote())
    assert "MOCK Situace v Gruzii" in src and "Georgia" in src and "usnesení" in src
    assert "500" not in src and "ADOPTED" not in src


def test_foreign_number_rejected():
    src = vs.vote_input(mock_vote())
    assert vs.summarize(Fake("Usnesení k Gruzii, pro hlasovalo 500 poslanců."), src) is None
    assert vs.summarize(Fake("Usnesení Parlamentu k situaci v Gruzii."), src) == "Usnesení Parlamentu k situaci v Gruzii."


def test_cache_reused_and_invalidated():
    fake = Fake("Usnesení Parlamentu k situaci v Gruzii.")
    out = vs.run([mock_vote()], {}, fake, "d")
    assert out["items"]["1"]["shrnuti"].startswith("Usnesení") and fake.calls == 1
    again = vs.run([mock_vote()], out, fake, "d")
    assert fake.calls == 1 and again["items"] == out["items"]
    changed = vs.run([mock_vote(title="MOCK other")], out, None, "d")  # změněný vstup bez backendu: shrnutí zmizí
    assert "1" not in changed["items"]


def test_api_backend_uses_vote_prompt():
    calls = []
    api = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **kw: calls.append(kw)
            or SimpleNamespace(
                stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps({"shrnuti": "Usnesení k Gruzii."}))]
            )
        )
    )
    b = vs.ApiBackend(api, prompt=vs.PROMPT, schema=vs.SCHEMA)
    assert vs.summarize(b, vs.vote_input(mock_vote())) == "Usnesení k Gruzii."
    assert calls[0]["system"] == vs.PROMPT


def test_missing_lists_home_votes_without_summary():
    votes = [mock_vote(1, date="2026-10-07"), mock_vote(2, date="2026-10-08")]
    out = vs.run(votes, {}, Fake("MOCK Usnesení Parlamentu k situaci v Gruzii."), "d")
    assert vs.missing(votes, out) == []
    assert [v["id"] for v in vs.missing(votes + [mock_vote(3, date="2026-10-09")], out)] == [3]
