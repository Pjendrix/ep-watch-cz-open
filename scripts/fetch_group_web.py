"""Oficiální weby politických skupin EP z Wikidat (data/group_web.json).

Wikidata jsou strukturovaná data pod CC0 s veřejným API (žádný scraping HTML). Skupina se najde podle názvu článku české Wikipedie
(data/manual/group_wiki.json), web je hodnota vlastnosti P856 („oficiální web“). Nic jiného se nepřebírá: žádné popisy, protože
úvodní věty článků obsahují politické charakteristiky, které web záměrně nepřebírá (bez hodnocení).

Chybějící položka nebo web = chyba formátu, soubor se nepřepíše. API je omezené (HTTP 429): skript čeká podle Retry-After.

Použití:
    python scripts/fetch_group_web.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.wikidata.org/w/api.php"
UA = "EPWatchCZ/1.0 (https://github.com/Pjendrix/ep-watch-cz-open; independent project, weekly fetch of EP group websites)"


class FormatError(Exception):
    pass


def parse_websites(payload: dict, titles: dict[str, str]) -> dict[str, dict]:
    """Odpověď wbgetentities → {kód skupiny: {web, wikidata}}. Každá skupina musí mít položku a https adresu webu (P856)."""
    if "entities" not in payload:
        raise FormatError("odpověď Wikidat nemá pole entities")
    by_title = {}
    for qid, e in payload["entities"].items():
        title = (e.get("sitelinks") or {}).get("cswiki", {}).get("title")
        if title and "missing" not in e:
            by_title[title] = (qid, e)
    out = {}
    for code, title in titles.items():
        if title not in by_title:
            raise FormatError(f"Wikidata nemají položku pro článek „{title}“ ({code})")
        qid, e = by_title[title]
        claims = [c for c in (e.get("claims") or {}).get("P856", []) if c.get("rank") != "deprecated"]
        claims.sort(key=lambda c: c.get("rank") != "preferred")
        urls = [c["mainsnak"]["datavalue"]["value"] for c in claims if c.get("mainsnak", {}).get("datavalue")]
        urls = [u for u in urls if u.startswith("https://")]
        if not urls:
            raise FormatError(f"položka {qid} ({code}) nemá oficiální web (P856) s adresou https")
        out[code] = {"web": urls[0], "wikidata": f"https://www.wikidata.org/wiki/{qid}"}
    return out


def fetch(titles: dict[str, str], retries: int = 4) -> dict:
    query = urllib.parse.urlencode({"action": "wbgetentities", "sites": "cswiki", "titles": "|".join(titles.values()),
                                    "props": "claims|sitelinks", "format": "json"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{API}?{query}", headers={"User-Agent": UA}), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == retries:
                raise FormatError(f"Wikidata vrátila HTTP {e.code}") from e
            time.sleep(min(int(e.headers.get("Retry-After") or 30 * (attempt + 1)), 300))
    raise FormatError("Wikidata neodpovídají")


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    args = p.parse_args(argv)
    try:
        cfg = json.loads((args.data_dir / "manual" / "group_wiki.json").read_text(encoding="utf-8"))
        titles = cfg["titles"]
        groups = parse_websites(fetch(titles), titles)
    except (FormatError, KeyError, OSError) as e:
        print(f"CHYBA: {e}; data/group_web.json zůstává beze změny", file=sys.stderr)
        return 2
    doc = {"updated": dt.datetime.now(dt.timezone.utc).date().isoformat(),
           "source": {"name": "Wikidata (vlastnost P856, oficiální web)", "url": "https://www.wikidata.org", "license": "CC0 1.0"},
           "groups": groups}
    (args.data_dir / "group_web.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"weby skupin: {len(groups)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
