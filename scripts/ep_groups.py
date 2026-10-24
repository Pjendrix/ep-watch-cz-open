"""Frakce českých poslanců k datu hlasování podle EP Open Data API, ne podle HowTheyVote (hromadné zadání 24. 10. 2026, úkol 2).

HowTheyVote bere frakci z dokumentů hlasování a změnu frakce může zachytit později (Konečná: v EP API v PfE od 21. 10. 2026,
v exportu HowTheyVote 2026-10-24 ještě NI). Pravidlo webu je frakce k datu hlasování; rozhoduje členství v data/meps.json.

- apply(): u českých pozic přepíše group_code na frakci z EP (v kódech HowTheyVote); původní hodnota zůstane v group_code_htv.
  Když EP k datu žádnou frakci nemá, zůstane hodnota z HowTheyVote. Funkce je idempotentní.
- conflicts(): rozpory pro stats.json → sources.group_conflicts (poslanec, období, HTV × EP, počet hlasování).
- majority_counts(): group_counts pro výpočet většiny frakce s poslanci z rozporu přesunutými do frakce podle EP.
  Zobrazované počty frakcí zůstávají přesně podle HowTheyVote (rozhodnutí autora 24. 10. 2026).
"""

from __future__ import annotations

from collections import Counter, defaultdict

POSITIONS = ["FOR", "AGAINST", "ABSTENTION", "DID_NOT_VOTE"]  # pořadí sloupců v group_counts
# „Hlasuje s frakcí“ z méně hlasování = ve frakci krátce, číslo se bude měnit (profil, duel)
SHORT_GROUP_VOTES = 500


def ep_group_on(mep: dict, day: str) -> str | None:
    """Kód frakce v EP API (PPE, VERTS-ALE, PFE…) k danému dni, jinak None."""
    hits = [g["code"] for g in mep.get("groups", []) if g["start"] <= day and (g["end"] is None or day <= g["end"])]
    return hits[0] if len(hits) == 1 else None


def code_map(meps: list[dict], votes: list[dict]) -> dict[str, str]:
    """Kód EP → kód HowTheyVote podle toho, jak se oba zdroje shodují u většiny hlasování (rozpor jednoho poslance mapu nezmění)."""
    by_id = {m["id"]: m for m in meps}
    pairs: dict[str, Counter] = defaultdict(Counter)
    for v in votes:
        for p in v["cz_positions"]:
            m = by_id.get(p["member_id"])
            htv = p.get("group_code_htv", p["group_code"])
            ep = ep_group_on(m, v["date"]) if m else None
            if ep and htv:
                pairs[ep][htv] += 1
    return {ep: c.most_common(1)[0][0] for ep, c in pairs.items()}


def apply(votes: list[dict], meps: list[dict]) -> None:
    by_id = {m["id"]: m for m in meps}
    to_htv = code_map(meps, votes)
    for v in votes:
        for p in v["cz_positions"]:
            m = by_id.get(p["member_id"])
            ep = ep_group_on(m, v["date"]) if m else None
            if ep is None or ep not in to_htv:
                continue
            htv = p.get("group_code_htv", p["group_code"])
            code = to_htv[ep]
            if code != htv:
                p["group_code_htv"] = htv
                p["group_code"] = code
            else:
                p.pop("group_code_htv", None)
                p["group_code"] = htv


def conflicts(votes: list[dict]) -> list[dict]:
    """Souvislé rozpory po poslancích: [{member_id, from, to, htv, ep, votes}], seřazené."""
    acc: dict[tuple, dict] = {}
    for v in votes:
        for p in v["cz_positions"]:
            if "group_code_htv" not in p:
                continue
            key = (p["member_id"], p["group_code_htv"], p["group_code"])
            row = acc.setdefault(key, {"member_id": key[0], "from": v["date"], "to": v["date"], "htv": key[1], "ep": key[2], "votes": 0})
            row["from"], row["to"] = min(row["from"], v["date"]), max(row["to"], v["date"])
            row["votes"] += 1
    return sorted(acc.values(), key=lambda r: (r["member_id"], r["from"]))


def majority_counts(vote: dict) -> dict[str, list[int]]:
    """group_counts s českými poslanci z rozporu přesunutými z frakce podle HowTheyVote do frakce podle EP (jen pro většinu)."""
    moved = [p for p in vote["cz_positions"] if "group_code_htv" in p]
    if not moved:
        return vote["group_counts"]
    counts = {k: list(row) for k, row in vote["group_counts"].items()}
    for p in moved:
        i = POSITIONS.index(p["position"])
        src = counts.get(p["group_code_htv"] or "")
        if src and src[i] > 0:
            src[i] -= 1
        if p["group_code"]:
            counts.setdefault(p["group_code"], [0, 0, 0, 0])[i] += 1
    return counts


def short_group(mep: dict, pair: list[int] | None) -> dict | None:
    """{since, votes}, když se „hlasuje s frakcí“ počítá z méně než SHORT_GROUP_VOTES hlasování; since = začátek prvního
    členství ve frakci (bez nezařazených). Jinak None."""
    if not pair or not 0 < pair[1] < SHORT_GROUP_VOTES:
        return None
    starts = sorted(g["start"] for g in mep.get("groups", []) if g["code"] != "NI")
    return {"since": starts[0] if starts else None, "votes": pair[1]}
