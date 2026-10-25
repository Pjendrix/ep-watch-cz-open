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
            create=lambda **kw: (
                calls.append(kw)
                or SimpleNamespace(
                    stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps({"shrnuti": "Usnesení k Gruzii."}))]
                )
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


# --- B1: shrnutí z přijatého textu (adopted_texts.py) --------------------------------------------------------


def adopted_vote(i=1):
    return {**mock_vote(i), "texts_adopted_reference": "P10_TA(2026)0342"}


def test_summary_from_adopted_text_records_source():
    fake = Fake("Parlament vyzývá Komisi k vypracování strategie.")
    texts = {"TA-10-2026-0342": "MOCK Evropský parlament vyzývá Komisi, aby vypracovala strategii."}
    out = vs.run([adopted_vote()], {}, fake, "2026-10-17", text_for=texts.get)
    item = out["items"]["1"]
    assert item["source"] == "adopted_text" and item["source_url"].endswith("TA-10-2026-0342_cs.pdf")
    assert "vypracovala strategii" in vs.vote_input(adopted_vote(), texts["TA-10-2026-0342"])


def test_missing_text_falls_back_to_title():
    fake = Fake("Usnesení Parlamentu k situaci v Gruzii.")
    out = vs.run([adopted_vote()], {}, fake, "2026-10-17", text_for=lambda ta: None)
    assert out["items"]["1"]["source"] == "title" and out["items"]["1"]["source_url"] is None


def test_text_appearing_later_regenerates_summary():
    fake = Fake("Usnesení Parlamentu k situaci v Gruzii.")
    first = vs.run([adopted_vote()], {}, fake, "2026-10-17", text_for=lambda ta: None)
    fake.text = "Parlament vyzývá k propuštění vězňů."
    second = vs.run([adopted_vote()], first, fake, "2026-10-18", text_for=lambda ta: "MOCK Parlament vyzývá k propuštění vězňů.")
    assert fake.calls == 2 and second["items"]["1"]["source"] == "adopted_text"
    vs.run([adopted_vote()], second, fake, "2026-10-19", text_for=lambda ta: "MOCK Parlament vyzývá k propuštění vězňů.")
    assert fake.calls == 2  # stejný vstup = z cache


def test_number_outside_text_is_rejected():
    fake = Fake("Parlament chce 40 nových míst.")
    out = vs.run([adopted_vote()], {}, fake, "2026-10-17", text_for=lambda ta: "MOCK Parlament chce nová místa.")
    assert "1" not in out["items"]
    fake.text = "Parlament chce 40 nových míst."
    out = vs.run([adopted_vote()], {}, fake, "2026-10-17", text_for=lambda ta: "MOCK Parlament chce 40 nových míst.")
    assert out["items"]["1"]["shrnuti"] == "Parlament chce 40 nových míst."


def test_network_error_keeps_old_summary():
    fake = Fake("Usnesení Parlamentu k situaci v Gruzii.")
    first = vs.run([adopted_vote()], {}, fake, "2026-10-17", text_for=lambda ta: None)

    def boom(ta):
        raise OSError("MOCK výpadek")

    second = vs.run([adopted_vote()], first, fake, "2026-10-18", text_for=boom, log=lambda m: None)
    assert second["items"]["1"] == first["items"]["1"] and fake.calls == 1
