"""Duel poslanců (zadání 24. 10. 2026, část B): čisté funkce pro data/duel.json a shardy „kde se rozešli“.

Metriky se berou ze stejných dat jako profil (build_web.build_profile), takže duel ukazuje stejná čísla jako p/{id}.html.
Shoda dvojice je ze stats.json (pairwise), rozpad podle témat a rozchody se počítají stejně jako v compute_stats:
jen poslanci v mandátu k datu hlasování (active_positions) a jen hlasy pro, proti, zdržel se. Žádné skóre, žádný vítěz.
"""

from __future__ import annotations

from ep_groups import short_group

from collections import defaultdict
from itertools import combinations

from compute_stats import VOTED, active_positions, topic_codes

DIVERGED_KEY = 10  # nejvýš tolik hlasování z key_votes, kde se rozešli (od nejnovějších)
AMENDMENTS_DEF = (
    "Pozměňovací návrhy ve výborech: PN, pod kterými je poslanec mezi autory, z oficiálních dokumentů PN v registru EP "
    "(PN s více autory se počítá každému, kompromisní PN a PN frakcí se nepočítají). Spolupodepsané PN v plénu: hromadné "
    "návrhy poslanců ke zprávám s nejméně 36 podpisy. Počet nevypovídá o kvalitě ani úspěchu."
)


def pair_key(a: int, b: int) -> str:
    """Kanonický klíč dvojice: menší ID první (stejně jako kanonická URL d/{a}-{b})."""
    lo, hi = sorted((int(a), int(b)))
    return f"{lo}-{hi}"


def ratio(pair: list[int] | None) -> float | None:
    return pair[0] / pair[1] if pair and pair[1] else None


def mep_metrics(prof: dict) -> dict:
    """Čísla duelu z profilu poslance (výstup build_profile). None = zdroj neuvádí nebo se nepočítá (frakce u nezařazených)."""
    t = prof["total"]
    ag = prof["against_group"]
    loyal_den = t["group_loyalty"][1]
    own = prof.get("own_work") or {}
    summary = own.get("summary") or {}
    count = lambda k: (summary.get(k) or {}).get("count") if own else None  # noqa: E731
    act, amd = prof.get("activity"), prof.get("amendments")
    return {
        "attendance": t["attendance"],
        "presence": [prof["presence"]["present"], prof["presence"]["days"]] if (prof.get("presence") or {}).get("days") else None,
        "group_loyalty": t["group_loyalty"] if loyal_den else None,
        "votes_in_mandate": t["attendance"][1],
        "positions": t["positions"],
        "against_group": [ag["count"], loyal_den] if loyal_den else None,
        "decisive": len(prof.get("decisive") or []),
        "reports": count("report"),
        "shadow_reports": count("shadow_report"),
        "opinions": count("opinion"),
        "shadow_opinions": count("shadow_opinion"),
        "motions": count("motion"),
        "joint_motions": count("joint_motion"),
        "questions": count("question"),
        "speeches": act["speeches"] if act else None,
        "amendments": amd["committee"]["total"] if amd else None,
        "amendments_cosigned": amd["plenary"]["cosigned"] if amd else None,
    }


def current_committees(mep: dict, day: str) -> list[dict]:
    """Výbory k danému dni bez náhradnictví (stejně jako hlavička profilu), seřazené podle kódu."""
    now = [c for c in mep.get("committees", []) if (not c.get("end") or c["end"] >= day) and c["role"] != "MEMBER_SUBSTITUTE"]
    return [
        {"code": c["code"], "name": c.get("name_cs") or c.get("name_en") or "", "role": c["role"]}
        for c in sorted(now, key=lambda c: c["code"])
    ]


def pair_topics(votes: list[dict], by_id: dict, topics: list[str]) -> dict[str, dict[str, list[int]]]:
    """Shoda dvojic po tématech (stejná témata jako stats.json): {klíč dvojice: {téma: [stejně, oba hlasovali]}}."""
    topic_set = set(topics)
    out: dict[str, dict[str, list[int]]] = defaultdict(lambda: {t: [0, 0] for t in topics})
    for v in votes:
        vt = [t for t in topic_codes(v) if t in topic_set]
        if not vt:
            continue
        voted = [p for p in active_positions(v, by_id) if p["position"] in VOTED]
        for a, b in combinations(sorted(voted, key=lambda p: p["member_id"]), 2):
            cells = out[pair_key(a["member_id"], b["member_id"])]
            for t in vt:
                cells[t][1] += 1
                cells[t][0] += a["position"] == b["position"]
    return dict(out)


def diverged(votes: list[dict], by_id: dict) -> dict[str, list[list]]:
    """Hlasování, kde jeden z dvojice hlasoval PRO a druhý PROTI (zdržení se nepočítá), od nejnovějších.
    Položka: [id hlasování, pozice menšího ID, pozice většího ID, frakce menšího ID, frakce většího ID] (frakce k datu hlasování)."""
    out: dict[str, list[list]] = defaultdict(list)
    for v in sorted(votes, key=lambda v: (v["date"], v["id"]), reverse=True):
        clear = sorted((p for p in active_positions(v, by_id) if p["position"] in ("FOR", "AGAINST")), key=lambda p: p["member_id"])
        for a, b in combinations(clear, 2):
            if a["position"] != b["position"]:
                out[pair_key(a["member_id"], b["member_id"])].append(
                    [v["id"], a["position"], b["position"], a["group_code"], b["group_code"]]
                )
    return dict(out)


def build_duel(
    meps: list[dict],
    profiles: dict[int, dict],
    summaries: dict[int, dict],
    stats: dict,
    votes: list[dict],
    key_ids: list[int],
    topic_labels: dict,
    vote_summary,
    day: str,
) -> dict:
    """data/duel.json: metriky poslanců, shoda a témata všech dvojic, rozchody v klíčových hlasováních (nejvýš DIVERGED_KEY)."""
    by_id = {m["id"]: m for m in meps}
    topics = [t["code"] for t in stats.get("topics", [])]
    by_topic = pair_topics(votes, by_id, topics)
    key = set(key_ids)
    div_key = diverged([v for v in votes if v["id"] in key], by_id)
    div_all = diverged(votes, by_id)
    votes_by_id = {v["id"]: v for v in votes}
    pairs, used = {}, set()
    for a, b in combinations(sorted(by_id), 2):
        k = pair_key(a, b)
        same_total = stats["meps"][str(a)]["pairwise"].get(str(b), [0, 0])
        rows = div_key.get(k, [])[:DIVERGED_KEY]
        used.update(r[0] for r in rows)
        pairs[k] = {
            "agreement": same_total,
            "topics": {t: c for t, c in by_topic.get(k, {}).items() if c[1]},
            "diverged_key": rows,
            "diverged_all": len(div_all.get(k, [])),
        }
    return {
        "sources": stats["sources"],
        "definitions": {
            **{
                k: stats["definitions"].get(k)
                for k in ("attendance", "presence", "group_loyalty", "pairwise", "against_group", "decisive_votes", "own_work", "speeches")
            },
            "amendments": AMENDMENTS_DEF,
        },
        "topics": [{"code": t["code"], "label": topic_labels.get(t["code"]) or t["label"]} for t in stats.get("topics", [])],
        "meps": [
            {
                **summaries[m["id"]],
                "committees": current_committees(m, day),
                "metrics": mep_metrics(profiles[m["id"]]),
                # ve frakci krátce: „proti většině frakce“ z malého vzorku (ep_groups.SHORT_GROUP_VOTES)
                "group_short": short_group(m, profiles[m["id"]]["total"]["group_loyalty"]),
            }
            for m in sorted(meps, key=lambda m: m.get("sort_label") or m["name"])
        ],
        "pairs": pairs,
        "votes": {str(i): {k: vote_summary(votes_by_id[i])[k] for k in ("id", "date", "title", "result", "is_main")} for i in sorted(used)},
    }


def pair_shards(votes: list[dict], meps: list[dict]) -> dict[str, dict]:
    """Shardy public/data/duel/{a}-{b}.json (vznikají při sestavení): všechna hlasování, kde se dvojice rozešla (PRO / PROTI).
    Řádky jako v diverged(); názvy a data hlasování si stránka dočte ze search.json (jinak by shardy měly desítky MB)."""
    by_id = {m["id"]: m for m in meps}
    return {k: {"pair": k, "fields": ["id", "a", "b", "ga", "gb"], "rows": rows} for k, rows in diverged(votes, by_id).items()}
