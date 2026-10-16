"""Stáhne z EP Open Data API všechny poslance zvolené za ČR v 10. volebním období.

Zdroj: https://data.europarl.europa.eu/api/v2 (CC BY 4.0).
Výstup: data/meps.json, na poslance ID, jméno, pohlaví, portrét, mandáty od–do, frakce,
české strany a výbory s daty od–do (historie změn), vše jen pro 10. období.

Použití:
    python scripts/fetch_meps.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

API = "https://data.europarl.europa.eu/api/v2"
FORMAT = {"format": "application/ld+json"}
TERM = 10
TERM_ORG = f"org/ep-{TERM}"
TERM_START = "2024-07-16"
COUNTRY = "CZ"
COUNTRY_URI = "http://publications.europa.eu/resource/authority/country/CZE"
PHOTO_CREDIT = "© European Union – Source: EP"
PROFILE_URL = "https://www.europarl.europa.eu/meps/cs/{id}"

# EP API: max. 500 dotazů za 5 minut na endpoint. 0,7 s mezi dotazy = max. ~430.
MIN_INTERVAL = 0.7
TIMEOUT = 120  # sekund; detail dokumentu pléna trvá i desítky sekund

ROLE_MANDATE = "def/ep-roles/MEMBER_PARLIAMENT"
CLS_GROUP = "def/ep-entities/EU_POLITICAL_GROUP"
CLS_PARTY = "def/ep-entities/NATIONAL_POLITICAL_GROUP"
CLS_COMMITTEE_PREFIX = "def/ep-entities/COMMITTEE_PARLIAMENTARY_"


class FormatError(RuntimeError):
    """Odpověď EP API nemá očekávaný formát."""


def require(obj: dict, keys, where: str) -> None:
    if not isinstance(obj, dict):
        raise FormatError(f"{where}: očekáván objekt, přišlo {type(obj).__name__}")
    missing = [k for k in keys if k not in obj]
    if missing:
        raise FormatError(
            f"{where}: chybí pole {missing}. Formát EP API se nejspíš změnil, "
            f"zkontroluj https://data.europarl.europa.eu/en/developer-corner/opendata-api"
        )


def first_item(payload, where: str) -> dict:
    require(payload, ["data"], where)
    data = payload["data"]
    if not isinstance(data, list) or len(data) != 1:
        raise FormatError(f"{where}: očekávána právě 1 položka v 'data', přišlo {len(data) if isinstance(data, list) else data!r}")
    return data[0]


def retry_after(response) -> float | None:
    value = (getattr(response, "headers", None) or {}).get("Retry-After")
    try:
        return min(float(value), 300.0) if value is not None else None
    except ValueError:
        return None


class EPClient:
    """Tenký klient EP API s throttlingem, opakováním a cache organizací na disku."""

    def __init__(self, cache_dir: Path | None = None, session: requests.Session | None = None,
                 min_interval: float = MIN_INTERVAL):
        self.session = session or requests.Session()
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self._last = 0.0
        self._bodies: dict[str, dict] = {}

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{API}/{path}"
        last = "bez odpovědi"
        for attempt in range(8):
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.session.get(url, params={**FORMAT, **(params or {})}, timeout=TIMEOUT)
            except (requests.Timeout, requests.ConnectionError) as e:
                # EP API u velkých dokumentů občas neodpoví včas: zkusit znovu, postupně déle
                last = type(e).__name__
                time.sleep(2 ** (attempt + 1))
                continue
            last = f"HTTP {r.status_code}"
            if r.status_code == 429:
                # Limit se počítá za 5 minut: čekat podle Retry-After, jinak postupně déle (celkem ~10 min).
                time.sleep(retry_after(r) or 30 * (attempt + 1))
                continue
            if r.status_code >= 500:
                time.sleep(2 ** (attempt + 1))
                continue
            r.raise_for_status()
            try:
                return r.json()
            except ValueError as e:
                raise FormatError(f"{url}: odpověď není JSON") from e
        raise RuntimeError(f"{url}: EP API opakovaně neodpovídá (naposledy {last})")

    def list_meps(self, term: int = TERM, country: str = COUNTRY, page: int = 50) -> list[dict]:
        out, offset = [], 0
        while True:
            payload = self.get("meps", {"parliamentary-term": term, "country-of-representation": country,
                                        "offset": offset, "limit": page})
            require(payload, ["data"], "GET /meps")
            batch = payload["data"]
            for item in batch:
                require(item, ["identifier", "label"], "GET /meps položka")
            out.extend(batch)
            if len(batch) < page:
                return out
            offset += page

    def get_mep(self, mep_id: str) -> dict:
        return first_item(self.get(f"meps/{mep_id}"), f"GET /meps/{mep_id}")

    def get_body(self, org: str) -> dict:
        """Organizace (frakce, strana, výbor). Cache v paměti i na disku."""
        body_id = org.removeprefix("org/")
        if body_id in self._bodies:
            return self._bodies[body_id]
        path = self.cache_dir / f"{body_id}.json" if self.cache_dir else None
        if path and path.exists():
            body = json.loads(path.read_text(encoding="utf-8"))
        else:
            body = first_item(self.get(f"corporate-bodies/{body_id}"), f"GET /corporate-bodies/{body_id}")
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        require(body, ["identifier", "label"], f"corporate-bodies/{body_id}")
        self._bodies[body_id] = body
        return body


def in_term(period: dict, since: str = TERM_START) -> bool:
    end = period.get("endDate")
    return end is None or end >= since


def _short(uri: str | None) -> str | None:
    return None if uri is None else uri.rsplit("/", 1)[-1]


def _lang(labels, lang: str) -> str | None:
    return labels.get(lang) if isinstance(labels, dict) else None


def parse_mep(person: dict, get_body) -> dict:
    """Převede detail poslance z EP API na záznam meps.json. get_body(org) vrací organizaci."""
    pid = person.get("identifier", "?")
    where = f"meps/{pid}"
    require(person, ["identifier", "label", "hasMembership"], where)
    if not isinstance(person["hasMembership"], list):
        raise FormatError(f"{where}: hasMembership není seznam")

    mandates, groups, parties, committees = [], [], [], []
    for m in person["hasMembership"]:
        require(m, ["organization", "memberDuring"], f"{where} membership")
        period = m["memberDuring"]
        require(period, ["startDate"], f"{where} membership {m.get('identifier')}")
        if not in_term(period):
            continue
        start, end = period["startDate"], period.get("endDate")
        role, cls, org = m.get("role"), m.get("membershipClassification"), m["organization"]

        if role == ROLE_MANDATE:
            if org != TERM_ORG:
                continue
            if COUNTRY_URI not in (m.get("represents") or []):
                raise FormatError(f"{where}: mandát {m.get('identifier')} nereprezentuje ČR")
            mandates.append({"start": start, "end": end, "mandate_id": m.get("notation_codictMandateId")})
        elif cls == CLS_GROUP:
            b = get_body(org)
            groups.append({
                "org_id": b["identifier"], "code": _short(b.get("isVersionOf")), "short_label": b["label"],
                "name_cs": _lang(b.get("prefLabel"), "cs"), "name_en": _lang(b.get("prefLabel"), "en"),
                "role": _short(role), "start": start, "end": end,
            })
        elif cls == CLS_PARTY:
            b = get_body(org)
            parties.append({
                "org_id": b["identifier"], "short_label": b["label"],
                "name": _lang(b.get("prefLabel"), "cs") or _lang(b.get("prefLabel"), "en"),
                "role": _short(role), "start": start, "end": end,
            })
        elif cls and cls.startswith(CLS_COMMITTEE_PREFIX):
            b = get_body(org)
            committees.append({
                "org_id": b["identifier"], "code": _short(b.get("isVersionOf")) or b["label"],
                "type": cls.removeprefix(CLS_COMMITTEE_PREFIX),
                "name_cs": _lang(b.get("prefLabel"), "cs"), "name_en": _lang(b.get("prefLabel"), "en"),
                "role": _short(role), "start": start, "end": end,
            })

    if not mandates:
        raise FormatError(f"{where}: poslanec nemá mandát v {TERM}. období za ČR")
    key = lambda x: (x["start"], x["end"] or "9999", x.get("org_id") or "")
    img = person.get("img")
    return {
        "id": int(person["identifier"]),
        "name": person["label"],
        "given_name": person.get("givenName"),
        "family_name": person.get("familyName"),
        "sort_label": person.get("sortLabel"),
        # MALE / FEMALE podle EP (pro správné tvary sloves na webu), jinak null
        "gender": _short(person.get("hasGender")),
        "photo_url": img,
        "photo_credit": PHOTO_CREDIT if img else None,
        "profile_url": PROFILE_URL.format(id=person["identifier"]),
        "source_url": f"{API}/meps/{person['identifier']}",
        "mandates": sorted(mandates, key=key),
        "groups": sorted(groups, key=key),
        "parties": sorted(parties, key=key),
        "committees": sorted(committees, key=key),
    }


def fetch(client: EPClient) -> dict:
    listed = client.list_meps()
    if not listed:
        raise FormatError("GET /meps nevrátil žádné poslance")
    meps = []
    for item in listed:
        print(f"poslanec {item['identifier']} {item['label']}", file=sys.stderr)
        meps.append(parse_mep(client.get_mep(item["identifier"]), client.get_body))
    ids = [m["id"] for m in meps]
    if len(ids) != len(set(ids)):
        raise FormatError("GET /meps vrátil duplicitní poslance")
    return {
        "source": {
            "name": "EP Open Data API v2",
            "url": f"{API}/meps?parliamentary-term={TERM}&country-of-representation={COUNTRY}",
            "license": "CC BY 4.0",
        },
        "term": TERM,
        "term_start": TERM_START,
        "country": COUNTRY,
        "meps": sorted(meps, key=lambda m: m["id"]),
    }


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=root / "data" / "meps.json")
    p.add_argument("--cache-dir", type=Path, default=root / ".cache" / "ep" / "corporate-bodies")
    args = p.parse_args(argv)
    try:
        data = fetch(EPClient(cache_dir=args.cache_dir))
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"uloženo {len(data['meps'])} poslanců do {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
