"""Stáhne jmenovitá hlasování z HowTheyVote exportu a uloží pozice českých poslanců.

Zdroj: https://github.com/HowTheyVote/data (ODbL), stabilní odkazy latest/download/*.csv.gz.
Výstup: data/votes/YYYY-MM.json, jedno hlasování = název, datum, výsledek, témata,
is_main, pozice každého českého poslance (frakce a strana k datu hlasování)
a počty hlasů každé frakce (group_counts, pro výpočet loajality).
data/votes/index.json: seznam měsíců a frakcí.

Použití:
    python scripts/fetch_votes.py                     # stáhne nejnovější export
    python scripts/fetch_votes.py --csv-dir cesta/    # použije už stažené CSV
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import requests

from labels_cs import translate
from benchmarks import compute_benchmarks, window_key
from delegations import compute_delegations
from vote_kinds import FINAL_KINDS, classify

BASE_URL = "https://github.com/HowTheyVote/data/releases/latest/download"
HTV_VOTE_URL = "https://howtheyvote.eu/votes/{id}"
TERM_START = "2024-07-16"
COUNTRY = "CZE"

POSITIONS = {"FOR", "AGAINST", "ABSTENTION", "DID_NOT_VOTE"}
# Možné výsledky podle HowTheyVote (VoteResult): přijato, zamítnuto, propadlo, staženo.
RESULTS = {"ADOPTED", "REJECTED", "LAPSED", "WITHDRAWN"}

# Očekávané sloupce každé tabulky. Chybějící sloupec = změna formátu = chyba.
TABLES = {
    "votes": [
        "id", "timestamp", "display_title", "reference", "description",
        "amendment_subject", "amendment_number", "is_main", "procedure_reference",
        "procedure_title", "procedure_type", "procedure_stage", "count_for",
        "count_against", "count_abstention", "count_did_not_vote", "result",
        "texts_adopted_reference",
    ],
    "member_votes": [
        "vote_id", "member_id", "position", "country_code", "group_code",
        "group_short_label", "national_party_id", "national_party_short_label",
    ],
    "eurovoc_concepts": ["id", "label"],
    "eurovoc_concept_votes": ["vote_id", "eurovoc_concept_id"],
    "oeil_subjects": ["code", "label"],
    "oeil_subject_votes": ["vote_id", "oeil_subject_code"],
    "geo_areas": ["code", "label", "iso_alpha_2"],
    "geo_area_votes": ["vote_id", "geo_area_code"],
    "responsible_committee_votes": ["vote_id", "committee_code"],
    "groups": ["code", "official_label", "label", "short_label"],
}

# Pořadí počtů v group_counts: [pro, proti, zdržel se, nehlasoval].
COUNT_ORDER = ["FOR", "AGAINST", "ABSTENTION", "DID_NOT_VOTE"]


class FormatError(RuntimeError):
    """Vstupní data nemají očekávaný formát."""


def check_columns(columns, table: str) -> None:
    missing = [c for c in TABLES[table] if c not in set(columns)]
    if missing:
        raise FormatError(
            f"{table}.csv: chybí sloupce {missing}. Formát HowTheyVote exportu se "
            f"nejspíš změnil, zkontroluj https://github.com/HowTheyVote/data/releases"
        )


def resolve_release_tag(session: requests.Session) -> str | None:
    """Zjistí tag releasu, na který ukazuje latest/download (z přesměrování)."""
    r = session.head(f"{BASE_URL}/votes.csv.gz", allow_redirects=False, timeout=30)
    location = r.headers.get("Location", "")
    parts = location.split("/releases/download/")
    if r.status_code not in (301, 302) or len(parts) != 2:
        return None
    return parts[1].split("/")[0]


def stored_release(out_dir: Path) -> str | None:
    """Tag releasu, ze kterého jsou data v repu (data/votes/index.json → source.release)."""
    path = out_dir / "index.json"
    if not path.exists():
        return None
    return ((json.loads(path.read_text(encoding="utf-8")).get("source") or {}).get("release"))


def release_is_new(latest: str | None, stored: str | None) -> bool:
    """Nový export = latest známe a liší se od uloženého. Neznámý latest (síť, změna GitHubu) není důvod spouštět běh."""
    return bool(latest) and latest != stored


def download(dest: Path) -> str | None:
    dest.mkdir(parents=True, exist_ok=True)
    with requests.Session() as s:
        tag = resolve_release_tag(s)
        for table in TABLES:
            url = f"{BASE_URL}/{table}.csv.gz"
            print(f"stahuji {url}", file=sys.stderr)
            with s.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(dest / f"{table}.csv.gz", "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
    return tag


def read_table(csv_dir: Path, table: str, **kwargs) -> pd.DataFrame:
    path = csv_dir / f"{table}.csv.gz"
    if not path.exists():
        path = csv_dir / f"{table}.csv"
    if not path.exists():
        raise FormatError(f"chybí soubor {table}.csv(.gz) v {csv_dir}")
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""], **kwargs)
    check_columns(df.columns, table)
    return df


def load_votes(csv_dir: Path, since: str = TERM_START) -> pd.DataFrame:
    v = read_table(csv_dir, "votes")
    ts = pd.to_datetime(v["timestamp"], format="ISO8601", errors="coerce")
    if ts.isna().any():
        bad = v.loc[ts.isna(), "timestamp"].head(3).tolist()
        raise FormatError(f"votes.csv: neplatný timestamp, např. {bad}")
    v = v[ts >= pd.Timestamp(since)].copy()
    v["id"] = v["id"].astype(int)
    if not v["id"].is_unique:
        raise FormatError("votes.csv: duplicitní id hlasování")
    bad_main = set(v["is_main"].dropna()) - {"True", "False"}
    if bad_main or v["is_main"].isna().any():
        raise FormatError(f"votes.csv: neočekávaná hodnota is_main {bad_main or 'prázdná'}")
    v["is_main"] = v["is_main"] == "True"
    bad_res = set(v["result"].dropna()) - RESULTS
    if bad_res:
        raise FormatError(f"votes.csv: neočekávaný výsledek {sorted(bad_res)}")
    for c in ("count_for", "count_against", "count_abstention", "count_did_not_vote"):
        v[c] = pd.to_numeric(v[c], errors="raise").astype(int)
    return v.sort_values(["timestamp", "id"])


def load_member_votes(csv_dir: Path, vote_ids: set[int], country: str = COUNTRY, all_rows: list | None = None,
                      country_counts: dict | None = None):
    """Načte member_votes po částech.

    Vrací (pozice poslanců daného státu, {vote_id: {group_code: [pro, proti, zdržel, nehlasoval]}}),
    počty frakcí jsou přes všechny poslance EP. Když je all_rows seznam, přidá do něj kompaktní
    řádky všech poslanců (pro srovnání s celým EP, scripts/benchmarks.py). Když je country_counts slovník,
    naplní ho počty hlasů po státech {vote_id: {stát: [pro, proti, zdržel, nehlasoval]}} (scripts/delegations.py).
    """
    path = csv_dir / "member_votes.csv.gz"
    if not path.exists():
        path = csv_dir / "member_votes.csv"
    if not path.exists():
        raise FormatError(f"chybí soubor member_votes.csv(.gz) v {csv_dir}")
    parts, counts = [], []
    reader = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""], chunksize=1_000_000)
    for chunk in reader:
        check_columns(chunk.columns, "member_votes")
        chunk = chunk[chunk["vote_id"].astype(int).isin(vote_ids)]
        bad = set(chunk["position"].dropna()) - POSITIONS
        if bad or chunk["position"].isna().any():
            raise FormatError(f"member_votes.csv: neočekávaná pozice {sorted(bad) or 'prázdná'}")
        counts.append(chunk.groupby(["vote_id", "group_code", "position"]).size())
        if country_counts is not None:
            for (vid, cc, position), n in chunk.groupby(["vote_id", "country_code", "position"]).size().items():
                row = country_counts.setdefault(int(vid), {}).setdefault(cc, [0, 0, 0, 0])
                row[COUNT_ORDER.index(position)] += int(n)
        if all_rows is not None:
            all_rows.append(chunk[["vote_id", "member_id", "position", "group_code"]].copy())
        parts.append(chunk[chunk["country_code"] == country])
    mv = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=TABLES["member_votes"])
    if mv.duplicated(["vote_id", "member_id"]).any():
        raise FormatError("member_votes.csv: duplicitní záznam poslanec × hlasování")
    mv["vote_id"] = mv["vote_id"].astype(int)
    mv["member_id"] = mv["member_id"].astype(int)

    group_counts: dict[int, dict[str, list[int]]] = {}
    if counts:
        total = pd.concat(counts).groupby(level=[0, 1, 2]).sum()
        for (vid, group, position), n in total.items():
            row = group_counts.setdefault(int(vid), {}).setdefault(group, [0, 0, 0, 0])
            row[COUNT_ORDER.index(position)] += int(n)
    return mv, group_counts


def load_topics(csv_dir: Path, vote_ids: set[int]) -> dict[int, dict[str, list]]:
    """Vrátí {vote_id: {"eurovoc": [...], "oeil": [...], "geo": [...], "committees": [...]}}."""
    topics: dict[int, dict[str, list]] = {}

    def add(links: pd.DataFrame, key_col: str, kind: str, labels: dict | None) -> None:
        links = links[links["vote_id"].astype(int).isin(vote_ids)]
        for vid, code in zip(links["vote_id"].astype(int), links[key_col]):
            item = code if labels is None else {"code": code, "label": labels.get(code)}
            topics.setdefault(vid, {}).setdefault(kind, []).append(item)

    ev = read_table(csv_dir, "eurovoc_concepts")
    add(read_table(csv_dir, "eurovoc_concept_votes"), "eurovoc_concept_id", "eurovoc",
        dict(zip(ev["id"], ev["label"])))
    oe = read_table(csv_dir, "oeil_subjects")
    add(read_table(csv_dir, "oeil_subject_votes"), "oeil_subject_code", "oeil",
        dict(zip(oe["code"], oe["label"])))
    geo = read_table(csv_dir, "geo_areas")
    add(read_table(csv_dir, "geo_area_votes"), "geo_area_code", "geo",
        dict(zip(geo["code"], geo["label"])))
    add(read_table(csv_dir, "responsible_committee_votes"), "committee_code", "committees", None)

    for t in topics.values():
        for kind, items in t.items():
            t[kind] = sorted(items, key=lambda x: x if isinstance(x, str) else x["code"])
    return topics


def _clean(value):
    """NaN/prázdné hodnoty z pandas -> None (v JSONu null)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


def _int_or_none(value):
    value = _clean(value)
    return None if value is None else int(value)


def build_months(votes: pd.DataFrame, mv: pd.DataFrame, topics: dict, release: str | None,
                 group_counts: dict | None = None) -> dict[str, dict]:
    group_counts = group_counts or {}
    by_vote = {vid: g.sort_values("member_id") for vid, g in mv.groupby("vote_id")}
    months: dict[str, dict] = {}
    for row in votes.itertuples(index=False):
        month = row.timestamp[:7]
        cz = by_vote.get(row.id)
        positions = [] if cz is None else [
            {
                "member_id": int(p.member_id),
                "position": p.position,
                "group_code": _clean(p.group_code),
                "national_party_id": _int_or_none(p.national_party_id),
                "national_party": _clean(p.national_party_short_label),
            }
            for p in cz.itertuples(index=False)
        ]
        t = topics.get(row.id, {})
        vote = {
            "id": int(row.id),
            "timestamp": row.timestamp,
            "date": row.timestamp[:10],
            "title": _clean(row.display_title),
            "reference": _clean(row.reference),
            "description": _clean(row.description),
            "amendment_subject": _clean(row.amendment_subject),
            "amendment_number": _clean(row.amendment_number),
            "is_main": bool(row.is_main),
            # typ hlasování a český popis podle pravidel (scripts/vote_kinds.py, scripts/labels_cs.py)
            **dict(zip(("vote_kind", "inverted"), classify({
                "is_main": bool(row.is_main), "description": _clean(row.description),
                "amendment_subject": _clean(row.amendment_subject), "amendment_number": _clean(row.amendment_number),
            }))),
            "description_cs": translate(_clean(row.description)),
            "procedure": {
                "reference": _clean(row.procedure_reference),
                "title": _clean(row.procedure_title),
                "type": _clean(row.procedure_type),
                "stage": _clean(row.procedure_stage),
            },
            "texts_adopted_reference": _clean(row.texts_adopted_reference),
            "result": _clean(row.result),
            "counts": {
                "for": int(row.count_for),
                "against": int(row.count_against),
                "abstention": int(row.count_abstention),
                "did_not_vote": int(row.count_did_not_vote),
            },
            "topics": {
                "eurovoc": t.get("eurovoc", []),
                "oeil": t.get("oeil", []),
                "geo": t.get("geo", []),
                "committees": t.get("committees", []),
            },
            "source_url": HTV_VOTE_URL.format(id=int(row.id)),
            "group_counts": dict(sorted(group_counts.get(int(row.id), {}).items())),
            "cz_positions": positions,
        }
        months.setdefault(month, {
            "month": month,
            "source": {
                "name": "HowTheyVote.eu",
                "url": "https://github.com/HowTheyVote/data",
                "license": "ODbL",
                "release": release,
            },
            "votes": [],
        })["votes"].append(vote)
    return months


def write_months(months: dict[str, dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for month, payload in sorted(months.items()):
        path = out_dir / f"{month}.json"
        # Jedno hlasování na řádek: malé soubory a čitelné diffy v gitu.
        dump = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
        head = {k: v for k, v in payload.items() if k != "votes"}
        lines = [dump(v) for v in payload["votes"]]
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump(head)[:-1] + ',"votes":[\n' + ",\n".join(lines) + "\n]}\n")


def write_index(months: dict[str, dict], groups: pd.DataFrame, out_dir: Path, release: str | None,
                oeil: pd.DataFrame | None = None) -> None:
    """index.json: seznam měsíců (pro web), frakce, které se v hlasováních vyskytují,
    a číselník témat OEIL (kód -> anglický název) pro souhrny podle témat."""
    used = {g for m in months.values() for v in m["votes"] for g in v["group_counts"]}
    index = {
        "source": next(iter(months.values()))["source"] if months else None,
        "months": [{"month": k, "votes": len(v["votes"])} for k, v in sorted(months.items())],
        "groups": [
            {"code": r.code, "label": _clean(r.label), "short_label": _clean(r.short_label),
             "official_label": _clean(r.official_label)}
            for r in groups.sort_values("code").itertuples(index=False) if r.code in used
        ],
        "oeil_subjects": {} if oeil is None else dict(sorted(zip(oeil["code"], oeil["label"]))),
    }
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def mandate_windows(meps_path: Path, since: str = TERM_START) -> dict[str, tuple[str, str | None]]:
    """Okna mandátu českých poslanců (od prvního začátku do posledního konce) kromě plného období, pro srovnání
    s mediánem EP za stejné období (benchmarks.py). Bez data/meps.json se mediány počítají jen za celé období."""
    if not meps_path.exists():
        return {}
    meps = json.loads(meps_path.read_text(encoding="utf-8"))["meps"]
    windows = {}
    for m in meps:
        start = min(x["start"] for x in m["mandates"])
        ends = [x["end"] for x in m["mandates"]]
        end = None if None in ends else max(ends)
        if start <= since and end is None:
            continue
        windows[window_key(start, end)] = (start, end)
    return windows


def run(csv_dir: Path, out_dir: Path, release: str | None, since: str = TERM_START,
        benchmarks_path: Path | None = None, delegations_path: Path | None = None) -> dict[str, dict]:
    votes = load_votes(csv_dir, since)
    ids = set(votes["id"])
    all_rows: list = []
    country_counts: dict = {}
    mv, group_counts = load_member_votes(csv_dir, ids, all_rows=all_rows, country_counts=country_counts)
    topics = load_topics(csv_dir, ids)
    groups = read_table(csv_dir, "groups")
    months = build_months(votes, mv, topics, release, group_counts)
    others = Counter(re.sub(r"\d+", "N", v["description"] or "(bez popisu)")
                     for m in months.values() for v in m["votes"] if v["vote_kind"] == "other")
    if others:
        print("typ hlasování 'other' (doplnit do vote_kinds.py?): " +
              "; ".join(f"{k} ×{n}" for k, n in others.most_common(10)), file=sys.stderr)
    write_months(months, out_dir)
    final_ids = {v["id"] for m in months.values() for v in m["votes"] if v["vote_kind"] in FINAL_KINDS}
    rows = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame(columns=["vote_id", "member_id", "position", "group_code"])
    bench = compute_benchmarks(zip(rows["vote_id"].astype(int), rows["member_id"].astype(int), rows["position"],
                                   [g if isinstance(g, str) and g else None for g in rows["group_code"]]),
                               group_counts, final_ids, windows=mandate_windows(out_dir.parent / "meps.json", since),
                               vote_dates={int(i): d[:10] for i, d in zip(votes["id"], votes["timestamp"])})
    bench["source"] = {"release": release}
    (benchmarks_path or out_dir.parent / "benchmarks.json").write_text(
        json.dumps(bench, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"srovnání s EP: medián docházky {bench['ep']['attendance']} ({bench['ep']['meps']} poslanců)", file=sys.stderr)
    vote_meta = [{"id": int(r.id), "date": r.timestamp[:10], "result": r.result, "is_final": int(r.id) in final_ids,
                  "counts": {"for": int(r.count_for), "against": int(r.count_against)}} for r in votes.itertuples()]
    deleg = compute_delegations(country_counts, vote_meta, own=COUNTRY)
    deleg["source"] = {"release": release}
    (delegations_path or out_dir.parent / "delegations.json").write_text(
        json.dumps(deleg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_index(months, groups, out_dir, release, read_table(csv_dir, "oeil_subjects"))
    print(
        f"hlasování: {len(votes)} (hlavních {int(votes['is_main'].sum())}), "
        f"CZ pozic: {len(mv)}, poslanců: {mv['member_id'].nunique()}, měsíců: {len(months)}",
        file=sys.stderr,
    )
    return months


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv-dir", type=Path, help="adresář s už staženými CSV (nic se nestahuje)")
    p.add_argument("--release", help="tag releasu pro --csv-dir (jinak null)")
    p.add_argument("--cache-dir", type=Path, default=root / ".cache" / "htv")
    p.add_argument("--out-dir", type=Path, default=root / "data" / "votes")
    p.add_argument("--check-release", action="store_true",
                   help="nic nestahuje, jen vypíše new=true|false (nový export HowTheyVote proti datům v repu)")
    args = p.parse_args(argv)

    if args.check_release:
        with requests.Session() as s:
            latest = resolve_release_tag(s)
        stored = stored_release(args.out_dir)
        print(f"HowTheyVote: nejnovější export {latest}, v repu {stored}", file=sys.stderr)
        print(f"new={'true' if release_is_new(latest, stored) else 'false'}")
        return 0

    if args.csv_dir:
        csv_dir, release = args.csv_dir, args.release
    else:
        csv_dir, release = args.cache_dir, download(args.cache_dir)
    try:
        run(csv_dir, args.out_dir, release)
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
