"""Předsedové politických skupin EP podle EP Open Data API v2 (zadání 20. 10. 2026, F1b).

Role předsedy (def/ep-roles/CHAIR) a spolupředsedy (CHAIR_CO) je v členství poslance ve skupině (hasMembership,
membershipClassification EU_POLITICAL_GROUP). API nemá seznam členů podle skupiny, proto: seznam současných poslanců
(GET /meps/show-current, 1 dotaz) a jejich detaily po dávkách (GET /meps/{id1},{id2},…, 100 na dotaz). Celkem asi
10 dotazů týdně, s odstupem podle limitu EP API (fetch_meps.EPClient). Skupina z API se páruje na kód HowTheyVote
přes isVersionOf organizace (org/PPE → EPP …), pevnou tabulkou níže; neznámá skupina je chyba.

Výstup data/group_chairs.json: {source, updated, groups: {kód: [{mep_id, name, country, role, gender, start}]}}.
Když API u skupiny předsedu nevrátí, je tam [] (nikdy odhad). Při výpadku API zůstane předchozí soubor (workflow).

Použití:
    python scripts/fetch_group_chairs.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from fetch_meps import API, CLS_GROUP, EPClient, FormatError, require

CHAIR_ROLES = {"def/ep-roles/CHAIR": "CHAIR", "def/ep-roles/CHAIR_CO": "CHAIR_CO"}
GENDER = {"MALE": "M", "FEMALE": "F"}
# isVersionOf politické skupiny v EP API → kód skupiny v HowTheyVote (data/groups.json „code“).
EP_TO_CODE = {
    "PPE": "EPP",
    "S-D": "SD",
    "PFE": "PFE",
    "ECR": "ECR",
    "RENEW": "RENEW",
    "VERTS-ALE": "GREEN_EFA",
    "THE-LEFT": "GUE_NGL",
    "ESN": "ESN",
}
BATCH = 100


def chairs_from(current: list[dict], details: list[dict], org_codes: dict[str, str], day: str) -> dict[str, list[dict]]:
    """Předsedové a spolupředsedové platní ke dni `day`. current: položky /meps/show-current (kvůli zemi zastoupení),
    details: detaily poslanců s hasMembership, org_codes: {"org/7150": "PFE"}. Vrací {kód: [...]} pro všechny skupiny."""
    country = {str(p["identifier"]): p.get("api:country-of-representation") for p in current}
    out: dict[str, list[dict]] = {code: [] for code in sorted(set(org_codes.values()))}
    for p in details:
        require(p, ["identifier", "hasMembership"], f"GET /meps/{p.get('identifier')}")
        for m in p["hasMembership"]:
            if m.get("membershipClassification") != CLS_GROUP or m.get("role") not in CHAIR_ROLES:
                continue
            period = m.get("memberDuring") or {}
            start, end = period.get("startDate"), period.get("endDate")
            if not start or start > day or (end and end < day):
                continue
            code = org_codes.get(m.get("organization"))
            if code is None:
                continue
            gender = str(p.get("hasGender") or "").rsplit("/", 1)[-1]
            name = " ".join(x for x in (p.get("givenName"), p.get("familyName")) if x) or p.get("label")
            out[code].append(
                {
                    "mep_id": int(p["identifier"]),
                    "name": name,
                    "country": country.get(str(p["identifier"])),
                    "role": CHAIR_ROLES[m["role"]],
                    "gender": GENDER.get(gender),
                    "start": start,
                }
            )
    for rows in out.values():
        rows.sort(key=lambda r: (r["role"] != "CHAIR", r["start"], r["name"]))
    return out


def group_orgs(client: EPClient, orgs: set[str]) -> tuple[dict[str, str], dict[str, dict]]:
    """{org/…: kód} pro politické skupiny, které se v členstvích objevily, a {kód: {org_id, name_cs}} (úřední český název
    skupiny z prefLabel, hodí se u skupin bez českých poslanců, u kterých ho data poslanců nemají)."""
    out, meta = {}, {}
    for org in sorted(orgs):
        body = client.get_body(org)
        version = str(body.get("isVersionOf") or "").removeprefix("org/")
        if version not in EP_TO_CODE:
            raise FormatError(f"{org}: neznámá politická skupina {version!r}, doplň EP_TO_CODE ve fetch_group_chairs.py")
        out[org] = EP_TO_CODE[version]
        meta[EP_TO_CODE[version]] = {"org_id": body["identifier"], "name_cs": (body.get("prefLabel") or {}).get("cs")}
    return out, meta


def fetch(client: EPClient, day: str) -> dict:
    payload = client.get("meps/show-current", {"offset": 0, "limit": 1000})
    require(payload, ["data"], "GET /meps/show-current")
    current = payload["data"]
    if not current:
        raise FormatError("GET /meps/show-current nevrátil žádné poslance")
    ids = [str(p["identifier"]) for p in current]
    details: list[dict] = []
    for i in range(0, len(ids), BATCH):
        part = client.get("meps/" + ",".join(ids[i : i + BATCH]))
        require(part, ["data"], "GET /meps/{ids}")
        details.extend(part["data"])
    if len(details) != len(ids):
        raise FormatError(f"GET /meps/{{ids}}: {len(details)} detailů pro {len(ids)} poslanců")
    orgs = {
        m["organization"]
        for p in details
        for m in p.get("hasMembership", [])
        if m.get("membershipClassification") == CLS_GROUP
        and m.get("role") in CHAIR_ROLES
        and not (m.get("memberDuring") or {}).get("endDate")
    }
    org_codes, meta = group_orgs(client, orgs)
    groups = chairs_from(current, details, org_codes, day)
    for code in EP_TO_CODE.values():
        groups.setdefault(code, [])
    return {
        "note": "Předsedové a spolupředsedové politických skupin EP podle rolí v EP Open Data API (hasMembership, CHAIR a CHAIR_CO). "
        "Prázdný seznam = API předsedu nevrátilo. Generuje scripts/fetch_group_chairs.py.",
        "source": {"name": "EP Open Data API v2", "url": f"{API}/meps/show-current", "license": "CC BY 4.0", "updated": day},
        "groups": dict(sorted(groups.items())),
        "group_meta": dict(sorted(meta.items())),
    }


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=root / "data" / "group_chairs.json")
    p.add_argument("--cache-dir", type=Path, default=root / ".cache" / "ep")
    args = p.parse_args(argv)
    try:
        doc = fetch(EPClient(cache_dir=args.cache_dir), dt.date.today().isoformat())
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = sum(len(v) for v in doc["groups"].values())
    print(f"předsedové skupin: {n} ({', '.join(f'{k} {len(v)}' for k, v in doc['groups'].items())})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
