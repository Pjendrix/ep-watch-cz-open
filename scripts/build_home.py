"""Data pro úvodní stránku (data/home.json, revize úvodu U1–U5).

- votes: pět nejnovějších závěrečných hlasování (vote_kind ve FINAL_KINDS, jako všude na webu), od nejnovějšího.
  Žádný redakční výběr. U každého tečky českých poslanců: hlas k datu hlasování (F pro, A proti, B zdržel se,
  N nehlasoval, X v den hlasování nebyl v mandátu), strana a frakce k datu hlasování.
  Tečky = poslanci v mandátu v den nejnovějšího z pěti hlasování, pořadí pevné pro všech pět hlasování
  (frakce podle GROUP_ORDER, pak strana, pak příjmení), aby se při přepnutí jen přebarvily.
  Téma (topics) ze stejné funkce jako čip v seznamu hlasování (categories_for).
- facts: čísla pro pruh faktů, „tři cesty“ a „další pohledy“, všechna přečtená z existujících JSON.

Nic se nepočítá nově kromě součtů; vstupy se ověří a při změně formátu skript skončí čitelnou chybou.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from compute_stats import FormatError, load_votes, require
from categories import LABEL as CAT_LABEL, categories_for
from vote_kinds import FINAL_KINDS, KIND_LABELS, kind_of

N_VOTES = 5
# Pořadí frakcí zleva doprava (stejné jako GROUP_ORDER v public/home.js, hemicykl delegace).
GROUP_ORDER = ["GUE_NGL", "SD", "GREEN_EFA", "RENEW", "EPP", "ECR", "PFE", "ESN", "NI"]
POS_CODE = {"FOR": "F", "AGAINST": "A", "ABSTENTION": "B", "DID_NOT_VOTE": "N"}


def _read(path: Path):
    if not path.exists():
        raise FormatError(f"chybí {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _name(m: dict) -> str:
    return f"{m['given_name']} {m['family_name']}" if m.get("given_name") and m.get("family_name") else m["name"]


def _in_mandate(m: dict, day: str) -> bool:
    return any(x["start"] <= day and (not x.get("end") or day <= x["end"]) for x in m["mandates"])


def latest_final(votes: list[dict], n: int = N_VOTES) -> list[dict]:
    """n nejnovějších závěrečných hlasování, od nejnovějšího (při stejném dni podle času, pak id)."""
    finals = [v for v in votes if kind_of(v) in FINAL_KINDS]
    finals.sort(key=lambda v: (v["date"], v.get("timestamp") or "", v["id"]), reverse=True)
    return finals[:n]


def build(data_dir: Path) -> dict:
    overview = _read(data_dir / "overview.json")
    require(overview, ["meps", "period", "sources"], "overview.json")
    parties = _read(data_dir / "parties.json")
    _, votes = load_votes(data_dir / "votes")
    picked = latest_final(votes)
    if not picked:
        raise FormatError("žádné závěrečné hlasování, úvod nemá co ukázat")
    for v in picked:
        require(v, ["id", "date", "title", "result", "cz_positions"], f"hlasování {v.get('id')}")
    meps = {m["id"]: m for m in overview["meps"]}
    independent = {str(p["id"]) for p in parties if p.get("independent")}

    newest = picked[0]
    by_id = {p["member_id"]: p for p in newest["cz_positions"]}
    seats = [m for m in overview["meps"] if _in_mandate(m, newest["date"])]

    def order(m: dict):
        p = by_id.get(m["id"], {})
        g = p.get("group_code") or (m.get("group") or {}).get("code") or "NI"
        return (GROUP_ORDER.index(g) if g in GROUP_ORDER else len(GROUP_ORDER), p.get("national_party") or "",
                m.get("sort_label") or m["name"])
    seats.sort(key=order)

    out_votes = []
    for v in picked:
        pos = {p["member_id"]: p for p in v["cz_positions"]}
        ppl = []
        for m in seats:
            p = pos.get(m["id"])
            if p and p["position"] not in POS_CODE:
                raise FormatError(f"hlasování {v['id']}: neznámá pozice {p['position']}")
            ppl.append({"id": m["id"], "name": _name(m),
                        "party": (p.get("national_party") if p else None),
                        "ind": bool(p and str(p.get("national_party_id")) in independent),
                        "group": (p.get("group_code") if p else None),
                        "pos": POS_CODE[p["position"]] if p else "X"})
        k = kind_of(v)
        out_votes.append({"id": v["id"], "date": v["date"], "month": v["date"][:7], "title": v["title"],
                          "kind": k, "kind_label": KIND_LABELS.get(k, k), "result": v.get("result"),
                          # téma ze stejné funkce jako čip v seznamu hlasování (categories.py), první = hlavní
                          "topics": [{"slug": c, "label": CAT_LABEL[c]} for c in categories_for(v)],
                          "counts": {c: sum(1 for x in ppl if x["pos"] == c) for c in "FABNX"}, "ppl": ppl})

    # --- čísla pro pruh faktů a další bloky (jen čtení existujících souborů) ---
    today_active = [m for m in overview["meps"] if any(not x.get("end") for x in m["mandates"])]
    party_ids = [str((m.get("party") or {}).get("org_id") or (m.get("party") or {}).get("id") or "") for m in today_active]
    named = {pid for pid in party_ids if pid and pid not in independent}
    no_party = sum(1 for pid in party_ids if not pid or pid in independent)
    splits = _read(data_dir / "splits.json")
    require(splits, ["unity"], "splits.json")
    unity = splits["unity"]
    require(unity, ["considered", "united_final", "considered_final"], "splits.json → unity")
    decisive = _read(data_dir / "decisive.json")
    require(decisive, ["votes"], "decisive.json")
    work = _read(data_dir / "work_hub.json")
    require(work, ["totals", "updated"], "work_hub.json")
    require(work["totals"], ["meps", "speeches", "questions", "reports_lead"], "work_hub.json → totals")
    index = _read(data_dir / "votes" / "index.json")
    release = overview["sources"]["votes"].get("release")
    facts = {
        "meps_active": len(today_active), "parties": len(named), "no_party": no_party,
        "votes_total": unity["considered"], "votes_from": overview["period"]["from"],
        "data_day": release if release and len(release) == 10 and release[4] == "-" else overview["period"]["to"],
        "monthly": [{"month": m["month"], "votes": m["votes"]} for m in index["months"]],
        "united_final": unity["united_final"], "considered_final": unity["considered_final"],
        "decisive": len(decisive["votes"]),
        "work": {"meps": work["totals"]["meps"], "speeches": work["totals"]["speeches"], "questions": work["totals"]["questions"],
                 "reports_lead": work["totals"]["reports_lead"], "updated": work["updated"]},
    }
    return {"note": "Pět nejnovějších závěrečných hlasování (bez výběru) a čísla pro úvodní stránku. Generuje scripts/build_home.py.",
            "votes": out_votes, "facts": facts}


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    args = p.parse_args(argv)
    try:
        home = build(args.data_dir)
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    (args.data_dir / "home.json").write_text(json.dumps(home, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"úvod: {len(home['votes'])} hlasování, {len(home['votes'][0]['ppl'])} teček", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
