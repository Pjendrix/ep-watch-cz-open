"""Srozumitelné shrnutí otázek kvízu „Moje shoda“ (Claude Haiku).

Úřední název typu „Změna nařízení (EU) 2023/2124…“ laik nepochopí. Pro každou otázku z data/quiz.json proto Claude Haiku
napíše krátký název a dvě věty, o čem zákon je. Vstup jsou jen údaje, které máme ze zdrojů (úřední český a anglický název,
popis hlasování z HowTheyVote, číslo a druh procedury); pokyny jsou v PROMPT a web je ukazuje celé (ⓘ u kvízu).

Pravidla (CLAUDE.md: AI jen shrnuje a překládá, čísla počítá kód):
  - shrnutí nesmí obsahovat číslo, které není ve vstupu (kontrola has_foreign_numbers); jinak se zahodí,
  - výsledek hlasování ani hodnocení zákona se do shrnutí nepíše (pokyn v PROMPT),
  - bez ANTHROPIC_API_KEY volá lokální Claude Code (`claude -p`, stejný model a zadání); bez obojího nic nevolá
    a web ukáže úřední název.
Shrnutí se cachují v data/quiz_summaries.json podle čísla procedury a otisku vstupu; znovu se volá jen nová nebo změněná otázka.

Použití:
    python scripts/quiz_summaries.py                       # lokálně přes Claude Code (předplatné, bez API klíče)
    ANTHROPIC_API_KEY=... python scripts/quiz_summaries.py # přes Claude API (např. GitHub Actions)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from categories import LABEL as CAT_LABEL
from compute_stats import FormatError, require

MODEL = "claude-haiku-5-5"
PROMPT_VERSION = 3
PROMPT = """Jsi editor českého nezávislého webu o hlasování europoslanců. Web má kvíz: čtenář řekne, jak by hlasoval o zákonu, a porovná se s poslanci.
Úřední názvy zákonů jsou pro laiky nesrozumitelné. Napiš ke každému zákonu:
- "nazev": krátký srozumitelný český název (nejvýš 80 znaků), ne otázka,
- "shrnuti": jednu až dvě věty (nejvýš 200 znaků), co zákon dělá a koho se týká.

Pravidla:
- Vycházej jen z údajů v zadání. Nic nedomýšlej; když z údajů není jasné, co zákon mění, převeď úřední název do srozumitelné češtiny a víc nepiš.
- Piš neutrálně: žádné hodnocení, žádné „kontroverzní“, „důležitý“, „sporný“, žádné argumenty pro ani proti.
- Nepiš, jak hlasování dopadlo, kdo jak hlasoval, ani žádné počty hlasů.
- Nepoužívej čísla, která nejsou v zadání (letopočty a čísla předpisů jen tak, jak jsou v zadání).
- Piš spisovnou češtinou bez zkratek, které laik nezná (EU a Komise jsou v pořádku); zkratky, které nejsou v zadání, nepřidávej.
- Nezmiňuj zadání, hlasování ani to, kdo o návrhu rozhoduje; popisuj jen obsah zákona. Nepiš výplňové věty."""
SCHEMA = {
    "type": "object",
    "properties": {"nazev": {"type": "string"}, "shrnuti": {"type": "string"}},
    "required": ["nazev", "shrnuti"],
    "additionalProperties": False,
}
PROCESS_TYPE = {"COD": "řádný legislativní postup", "CNS": "konzultace (rozhoduje Rada)", "APP": "souhlas Parlamentu"}
NUM_RE = re.compile(r"\d+")


def question_input(q: dict) -> str:
    """Zadání pro model: jen údaje ze zdrojů (bez výsledku a počtů hlasů)."""
    ptype = q["procedure"].rsplit("(", 1)[-1].rstrip(")")
    lines = [f"Úřední český název: {q['title']}"]
    if q.get("title_en") and q["title_en"] != q["title"]:
        lines.append(f"Anglický název procedury: {q['title_en']}")
    if q.get("description"):
        lines.append(f"Popis hlasování: {q['description']}")
    lines.append(f"Procedura: {q['procedure']} ({PROCESS_TYPE.get(ptype, ptype)})")
    if q.get("topic") in CAT_LABEL:
        lines.append(f"Téma: {CAT_LABEL[q['topic']]}")
    return "\n".join(lines)


def fingerprint(text: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}\n{MODEL}\n{PROMPT}\n{text}".encode()).hexdigest()[:16]


def has_foreign_numbers(output: str, source: str) -> bool:
    """Číslo ve shrnutí, které ve vstupu není (pravidlo: čísla nevkládá AI)."""
    allowed = set(NUM_RE.findall(source))
    return any(n not in allowed for n in NUM_RE.findall(output))


def valid(summary: dict, source: str) -> bool:
    nazev, shrnuti = summary.get("nazev", "").strip(), summary.get("shrnuti", "").strip()
    return (0 < len(nazev) <= 100 and 0 < len(shrnuti) <= 220
            and not has_foreign_numbers(f"{nazev} {shrnuti}", source))


class ApiBackend:
    """Claude API (ANTHROPIC_API_KEY), např. v GitHub Actions."""

    def __init__(self, client):
        self.client = client

    def ask(self, text: str) -> dict | None:
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=PROMPT,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": text}],
        )
        if response.stop_reason != "end_turn":
            return None
        raw = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None


class CliBackend:
    """Claude Code (`claude -p`) s přihlášeným předplatným nebo tokenem z `claude setup-token`; bez API klíče.
    Stejný model, zadání (nahrazuje výchozí systémový prompt Claude Code) a schéma výstupu; bez nástrojů a mimo repo,
    aby model neviděl nic kromě zadání."""

    def __init__(self, cmd: str = "claude", timeout: int = 180):
        self.cmd, self.timeout = cmd, timeout

    def ask(self, text: str) -> dict | None:
        with tempfile.TemporaryDirectory() as tmp:
            res = subprocess.run(
                [self.cmd, "-p", "--model", MODEL, "--output-format", "json", "--tools=", "--system-prompt", PROMPT,
                 "--json-schema", json.dumps(SCHEMA)],
                input=text, capture_output=True, text=True, timeout=self.timeout, cwd=tmp)
        if res.returncode != 0:
            return None
        try:
            out = json.loads(res.stdout)
        except json.JSONDecodeError:
            return None
        if out.get("is_error") or (out.get("modelUsage") and MODEL not in out["modelUsage"]):
            return None  # chyba nebo odpověděl jiný model, než který web uvádí
        return out.get("structured_output") if isinstance(out.get("structured_output"), dict) else None


def summarize(backend, text: str) -> dict | None:
    """Jedno volání Haiku; None při odmítnutí, chybě nebo neplatném výstupu."""
    data = backend.ask(text)
    if not isinstance(data, dict) or not isinstance(data.get("nazev"), str) or not isinstance(data.get("shrnuti"), str):
        return None
    return {"nazev": data["nazev"].strip(), "shrnuti": data["shrnuti"].strip()} if valid(data, text) else None


def run(quiz: dict, cache: dict, client, today: str, log=print) -> dict:
    """Doplní shrnutí k otázkám kvízu; vrací nový obsah data/quiz_summaries.json (jen pro otázky v kvízu)."""
    require(quiz, ["questions"], "quiz.json")
    old = cache.get("items", {})
    items: dict[str, dict] = {}
    for q in quiz["questions"]:
        require(q, ["procedure", "title"], "quiz.json otázka")
        text = question_input(q)
        fp = fingerprint(text)
        if old.get(q["procedure"], {}).get("fingerprint") == fp:
            items[q["procedure"]] = old[q["procedure"]]
            continue
        if client is None:
            continue
        summary = summarize(client, text)
        if summary is None:
            log(f"{q['procedure']}: shrnutí zamítnuto (odmítnutí, neplatný výstup nebo číslo mimo zadání), web ukáže úřední název")
            continue
        items[q["procedure"]] = {**summary, "fingerprint": fp, "generated": today}
    return {"note": "Shrnutí otázek kvízu Moje shoda od Claude Haiku (scripts/quiz_summaries.py). Čísla ani výsledky hlasování neobsahují.",
            "model": MODEL, "prompt_version": PROMPT_VERSION, "prompt": PROMPT, "items": items}


def missing(quiz: dict, cache: dict) -> list[dict]:
    """Otázky kvízu bez platného shrnutí (nové, změněné nebo po změně zadání)."""
    items = cache.get("items", {})
    return [q for q in quiz.get("questions", [])
            if items.get(q["procedure"], {}).get("fingerprint") != fingerprint(question_input(q))]


def check_output(quiz: dict, cache: dict) -> str:
    """Výstup pro GITHUB_OUTPUT: missing=N a seznam otázek (pro upozornění v issue)."""
    miss = missing(quiz, cache)
    lines = "\n".join(f"- {q['title']} ({q['procedure']})" for q in miss)
    return f"missing={len(miss)}\nlist<<EOF_LIST\n{lines}\nEOF_LIST\n"


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    p.add_argument("--backend", choices=["auto", "api", "claude-cli"], default="auto",
                   help="api = ANTHROPIC_API_KEY; claude-cli = lokální Claude Code bez API klíče; auto = api, když je klíč, jinak claude-cli")
    p.add_argument("--check", action="store_true", help="nic negeneruje, jen vypíše počet otázek bez shrnutí (GITHUB_OUTPUT)")
    args = p.parse_args(argv)
    quiz_path, out_path = args.data_dir / "quiz.json", args.data_dir / "quiz_summaries.json"
    if not quiz_path.exists():
        print("chybí data/quiz.json, spusť nejdřív build_web.py", file=sys.stderr)
        return 2
    if args.check:
        cache = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
        print(check_output(json.loads(quiz_path.read_text(encoding="utf-8")), cache), end="")
        return 0
    client = None
    use_api = args.backend == "api" or (args.backend == "auto" and os.environ.get("ANTHROPIC_API_KEY"))
    if use_api and os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic  # jen když se opravdu volá API
        client = ApiBackend(anthropic.Anthropic())
    elif not use_api and shutil.which("claude"):
        client = CliBackend()
        print("shrnutí přes Claude Code (claude -p), bez API klíče", file=sys.stderr)
    else:
        print("chybí ANTHROPIC_API_KEY i Claude Code: nová shrnutí se nevytvoří, zůstanou jen uložená", file=sys.stderr)
    cache = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    try:
        out = run(json.loads(quiz_path.read_text(encoding="utf-8")), cache, client, dt.date.today().isoformat(),
                  log=lambda m: print(m, file=sys.stderr))
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"shrnutí kvízu: {len(out['items'])} z {len(json.loads(quiz_path.read_text(encoding='utf-8'))['questions'])} otázek",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
