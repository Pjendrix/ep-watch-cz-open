"""Krátké AI shrnutí hlasování na úvodní stránce (Claude Haiku), data/vote_summaries.json.

Karta „Poslední hlasování“ na úvodu ukazuje pod nadpisem 1–2 věty, o čem se hlasovalo. Vstup jsou jen údaje ze zdrojů
(úřední český a anglický název, druh procedury, popis hlasování, témata EuroVoc/OEIL a země z HowTheyVote). Stejné
pojistky jako u kvízu (quiz_summaries.py, CLAUDE.md: AI jen shrnuje a překládá, čísla počítá kód):
  - číslo, které není ve vstupu, shrnutí zahodí (has_foreign_numbers),
  - výsledek, počty hlasů ani hodnocení se do shrnutí nepíšou (pokyn v PROMPT),
  - bez ANTHROPIC_API_KEY volá lokální Claude Code (`claude -p`); bez obojího nic nevolá a karta ukáže jen nadpis.
Shrnutí se cachují podle id hlasování a otisku vstupu; znovu se volá jen nové nebo změněné hlasování.

Použití (po build_web.py, před build_pages.py – úvod je statický):
    python scripts/vote_summaries.py                       # lokálně přes Claude Code
    ANTHROPIC_API_KEY=... python scripts/vote_summaries.py --backend api
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from build_home import latest_final
from compute_stats import FormatError, load_votes, require
from quiz_summaries import MODEL, NUM_RE, ApiBackend, CliBackend
from vote_kinds import KIND_LABELS, kind_of

PROMPT_VERSION = 1
N_VOTES = 10  # pět na úvodu + rezerva, aby po novém zasedání nebyla karta bez shrnutí
PROMPT = """Jsi editor českého nezávislého webu o hlasování europoslanců. Na úvodní stránce je karta posledního hlasování
s úředním názvem. Napiš pod něj "shrnuti": jednu až dvě krátké věty (nejvýš 180 znaků), o čem se hlasovalo, srozumitelně pro laika.

Pravidla:
- Vycházej jen z údajů v zadání. Nic nedomýšlej: obsah textu, který v zadání není, nepopisuj. Když údaje říkají jen téma,
  napiš jen, čeho se text týká (např. „Usnesení Parlamentu k situaci politických vězňů v Ázerbájdžánu.“) a víc nepiš.
- Neopakuj doslova nadpis; přidej druh textu (usnesení, zákon, rozpočet…) a koho nebo čeho se týká.
- Piš neutrálně: žádné hodnocení, žádné „kontroverzní“, „důležitý“, „sporný“, žádné argumenty pro ani proti.
- Nepiš, jak hlasování dopadlo, kdo jak hlasoval, ani žádné počty hlasů.
- Nepoužívej čísla, která nejsou v zadání.
- Spisovná čeština, bez zkratek, které laik nezná (EU a Komise jsou v pořádku). Nepiš výplňové věty."""
SCHEMA = {
    "type": "object",
    "properties": {"shrnuti": {"type": "string"}},
    "required": ["shrnuti"],
    "additionalProperties": False,
}
PROCESS_TYPE = {
    "COD": "zákon, řádný legislativní postup",
    "CNS": "zákon, konzultace (rozhoduje Rada)",
    "APP": "souhlas Parlamentu",
    "RSP": "usnesení Parlamentu (nezávazné)",
    "INI": "zpráva z vlastního podnětu (nezávazná)",
    "BUD": "rozpočet EU",
    "NLE": "nelegislativní akt",
    "DEC": "rozhodnutí",
    "RPS": "námitka k prováděcímu aktu",
    "DEA": "námitka k aktu v přenesené pravomoci",
}


def vote_input(v: dict) -> str:
    """Zadání pro model: jen údaje ze zdrojů (bez výsledku a počtů hlasů)."""
    proc = v.get("procedure") or {}
    lines = []
    if v.get("title_cs"):
        lines.append(f"Úřední český název: {v['title_cs']}")
    lines.append(f"Anglický název: {proc.get('title') or v['title']}")
    k = kind_of(v)
    lines.append(f"Druh hlasování: {KIND_LABELS.get(k, k)}")
    if v.get("description_cs"):
        lines.append(f"Popis hlasování: {v['description_cs']}")
    if proc.get("reference"):
        ptype = proc.get("type") or proc["reference"].rsplit("(", 1)[-1].rstrip(")")
        lines.append(f"Procedura: {proc['reference']} ({PROCESS_TYPE.get(ptype, ptype)})")
    t = v.get("topics") or {}
    if t.get("oeil"):
        lines.append("Oblast (Legislativní observatoř EP): " + "; ".join(x["label"].strip() for x in t["oeil"]))
    if t.get("eurovoc"):
        lines.append("Klíčová slova EuroVoc: " + ", ".join(x["label"] for x in t["eurovoc"]))
    if t.get("geo"):
        lines.append("Země: " + ", ".join(x["label"] for x in t["geo"]))
    return "\n".join(lines)


def fingerprint(text: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}\n{MODEL}\n{PROMPT}\n{text}".encode()).hexdigest()[:16]


def valid(text: str, source: str) -> bool:
    allowed = set(NUM_RE.findall(source))
    return 0 < len(text) <= 200 and not any(n not in allowed for n in NUM_RE.findall(text))


def summarize(backend, source: str) -> str | None:
    data = backend.ask(source)
    if not isinstance(data, dict) or not isinstance(data.get("shrnuti"), str):
        return None
    text = data["shrnuti"].strip()
    return text if valid(text, source) else None


def run(votes: list[dict], cache: dict, backend, today: str, log=print) -> dict:
    """Shrnutí pro n nejnovějších závěrečných hlasování; starší platná shrnutí z cache zůstávají."""
    old = cache.get("items", {}) if cache.get("prompt_version") == PROMPT_VERSION else {}
    items = dict(old)
    for v in latest_final(votes, N_VOTES):
        require(v, ["id", "title"], "hlasování")
        key, source = str(v["id"]), vote_input(v)
        fp = fingerprint(source)
        if old.get(key, {}).get("fingerprint") == fp:
            continue
        items.pop(key, None)  # změněný vstup: staré shrnutí už neplatí
        if backend is None:
            continue
        text = summarize(backend, source)
        if text is None:
            log(f"{key}: shrnutí zamítnuto (odmítnutí, neplatný výstup nebo číslo mimo zadání), karta ukáže jen nadpis")
            continue
        items[key] = {"shrnuti": text, "fingerprint": fp, "generated": today}
    return {
        "note": "Krátká shrnutí posledních závěrečných hlasování od Claude Haiku (scripts/vote_summaries.py). "
        "Čísla ani výsledky hlasování neobsahují.",
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "prompt": PROMPT,
        "items": dict(sorted(items.items(), key=lambda kv: int(kv[0]), reverse=True)),
    }


def missing(votes: list[dict], cache: dict, n: int = 5) -> list[dict]:
    """Hlasování na úvodu (n nejnovějších závěrečných) bez platného shrnutí."""
    items = cache.get("items", {}) if cache.get("prompt_version") == PROMPT_VERSION else {}
    return [v for v in latest_final(votes, n) if items.get(str(v["id"]), {}).get("fingerprint") != fingerprint(vote_input(v))]


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    p.add_argument("--backend", choices=["auto", "api", "claude-cli"], default="auto")
    p.add_argument("--check", action="store_true", help="nic negeneruje, jen vypíše hlasování na úvodu bez shrnutí (GITHUB_OUTPUT)")
    args = p.parse_args(argv)
    out_path = args.data_dir / "vote_summaries.json"
    if args.check:
        cache = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
        miss = missing(load_votes(args.data_dir / "votes")[1], cache)
        lines = "\n".join(f"- {v.get('title_cs') or v['title']} ({v['date']})" for v in miss)
        print(f"missing_votes={len(miss)}\nlist_votes<<EOF_LIST\n{lines}\nEOF_LIST")
        return 0
    backend = None
    use_api = args.backend == "api" or (args.backend == "auto" and os.environ.get("ANTHROPIC_API_KEY"))
    if use_api and os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic  # jen když se opravdu volá API

        backend = ApiBackend(anthropic.Anthropic(), prompt=PROMPT, schema=SCHEMA)
    elif not use_api and shutil.which("claude"):
        backend = CliBackend(prompt=PROMPT, schema=SCHEMA)
        print("shrnutí přes Claude Code (claude -p), bez API klíče", file=sys.stderr)
    else:
        print("chybí ANTHROPIC_API_KEY i Claude Code: nová shrnutí se nevytvoří, zůstanou jen uložená", file=sys.stderr)
    cache = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    try:
        _, votes = load_votes(args.data_dir / "votes")
        out = run(votes, cache, backend, dt.date.today().isoformat(), log=lambda m: print(m, file=sys.stderr))
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"shrnutí hlasování: {len(out['items'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
