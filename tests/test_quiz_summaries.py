import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import quiz_summaries as qs  # noqa: E402

Q = {
    "id": 1,
    "procedure": "2025/0524(COD)",
    "title": "MOCK Změna nařízení (EU) 2021/1119 o klimatu do roku 2040",
    "title_en": "MOCK climate law",
    "description": "Prozatímní dohoda",
    "topic": "env",
}


class FakeApi:
    def __init__(self, payload, stop="end_turn"):
        self.payload, self.stop, self.calls = payload, stop, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=text)])


def FakeClient(payload, stop="end_turn"):
    return qs.ApiBackend(FakeApi(payload, stop))


def quiz(*qs_):
    return {"questions": list(qs_)}


def test_input_has_no_result_or_counts():
    text = qs.question_input({**Q, "result": "ADOPTED", "counts": [1, 2, 3], "positions": {"1": "F"}})
    assert "MOCK Změna nařízení" in text and "2025/0524(COD)" in text and "řádný legislativní postup" in text
    assert "ADOPTED" not in text and "přijat" not in text


def test_summary_stored_with_prompt_and_reused():
    client = FakeClient({"nazev": "MOCK Klimatický cíl EU do roku 2040", "shrnuti": "MOCK Zákon mění klimatický cíl EU."})
    out = qs.run(quiz(Q), {}, client, "2026-10-17")
    item = out["items"]["2025/0524(COD)"]
    assert item["nazev"] == "MOCK Klimatický cíl EU do roku 2040" and item["generated"] == "2026-10-17"
    assert out["prompt"] == qs.PROMPT and out["model"] == qs.MODEL == "claude-haiku-5-5"
    call = client.client.calls[0]
    assert call["system"] == qs.PROMPT and call["output_config"]["format"]["type"] == "json_schema"
    # podruhé se stejný vstup nevolá znovu
    client2 = FakeClient({"nazev": "x", "shrnuti": "y"})
    again = qs.run(quiz(Q), out, client2, "2026-10-18")
    assert client2.client.calls == [] and again["items"] == out["items"]


def test_changed_input_regenerates_and_removed_question_drops():
    out = qs.run(quiz(Q), {}, FakeClient({"nazev": "MOCK A", "shrnuti": "MOCK a."}), "2026-10-17")
    out2 = qs.run(quiz({**Q, "title": "MOCK nový název"}), out, FakeClient({"nazev": "MOCK B", "shrnuti": "MOCK b."}), "2026-10-18")
    assert out2["items"]["2025/0524(COD)"]["nazev"] == "MOCK B"
    assert qs.run(quiz(), out2, None, "2026-10-19")["items"] == {}


def test_numbers_not_in_input_are_rejected():
    bad = FakeClient({"nazev": "MOCK Klima", "shrnuti": "MOCK Emise klesnou o 90 procent."})
    assert qs.run(quiz(Q), {}, bad, "2026-10-17")["items"] == {}
    ok = FakeClient({"nazev": "MOCK Klima 2040", "shrnuti": "MOCK Mění předpis 2021/1119."})
    assert "2025/0524(COD)" in qs.run(quiz(Q), {}, ok, "2026-10-17")["items"]


def test_refusal_invalid_json_and_no_client_give_no_summary():
    assert qs.run(quiz(Q), {}, FakeClient({"nazev": "a", "shrnuti": "b"}, stop="refusal"), "d")["items"] == {}
    assert qs.run(quiz(Q), {}, FakeClient("není json"), "d")["items"] == {}
    assert qs.run(quiz(Q), {}, None, "d")["items"] == {}


def test_cli_backend_reads_structured_output(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw["input"]
        out = {
            "is_error": False,
            "structured_output": {"nazev": "MOCK Klima", "shrnuti": "MOCK Zákon o klimatu."},
            "modelUsage": {qs.MODEL: {}},
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(out))

    monkeypatch.setattr(qs.subprocess, "run", fake_run)
    out = qs.run(quiz(Q), {}, qs.CliBackend(), "2026-10-17")
    assert out["items"]["2025/0524(COD)"]["nazev"] == "MOCK Klima"
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == qs.MODEL
    assert seen["cmd"][seen["cmd"].index("--system-prompt") + 1] == qs.PROMPT and "--tools=" in seen["cmd"]
    assert "MOCK Změna nařízení" in seen["input"]


def test_cli_backend_rejects_other_model_and_errors(monkeypatch):
    def run_with(out, code=0):
        monkeypatch.setattr(qs.subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=code, stdout=json.dumps(out)))
        return qs.run(quiz(Q), {}, qs.CliBackend(), "d")["items"]

    ok = {"nazev": "MOCK", "shrnuti": "MOCK."}
    assert run_with({"structured_output": ok, "modelUsage": {"claude-opus-5-5": {}}}) == {}
    assert run_with({"is_error": True, "structured_output": ok}) == {}
    assert run_with({"structured_output": ok}, code=1) == {}


def test_check_lists_questions_without_summary():
    Q2 = {**Q, "procedure": "2025/0001(COD)", "title": "MOCK druhý"}
    out = qs.run(quiz(Q), {}, FakeClient({"nazev": "MOCK A", "shrnuti": "MOCK a."}), "d")
    assert [q["procedure"] for q in qs.missing(quiz(Q, Q2), out)] == ["2025/0001(COD)"]
    text = qs.check_output(quiz(Q, Q2), out)
    assert text.startswith("missing=1\n") and "- MOCK druhý (2025/0001(COD))" in text
    assert qs.check_output(quiz(Q), out).startswith("missing=0\n")
