"""Politické skupiny EP („evropské frakce“): souhrn hlasování celé skupiny v Evropském parlamentu.

Čísla se počítají z group_counts u každého hlasování (HowTheyVote: počty hlasů pro / proti / zdržel se / nehlasoval za skupinu),
tedy za všechny poslance skupiny, ne jen za české. Definice stejně jako u českých stran, jen přizpůsobené velikosti skupiny:
- Účast skupiny = podíl hlasů pro / proti / zdržel se z všech hlasů členů skupiny.
- Soudržnost = podíl hlasů pro a proti, které odpovídají většině skupiny (v hlasováních, kde pro/proti hlasovalo aspoň 10 členů).
- Výrazně rozdělená hlasování = menšina mezi hlasy pro a proti tvoří aspoň 30 % (stejný práh jako u české delegace).
Žádné pořadí ani hodnocení; Nezařazení (NI) nejsou skupina, proto tu nejsou.
"""

from __future__ import annotations

from vote_kinds import is_final

MIN_VOTERS = 10
STRONG_SPLIT = 0.3
SPLIT_LIMIT = 50


def _blank() -> dict:
    return {"attendance": [0, 0], "attendance_main": [0, 0], "majority": [0, 0], "majority_main": [0, 0],
            "splits": 0, "splits_main": 0, "considered": 0, "considered_main": 0, "_split_rows": []}


def build_group_stats(votes: list[dict], skip: tuple[str, ...] = ("NI",)) -> dict[str, dict]:
    """{kód skupiny: statistiky}; _split_rows = [(menšina, id hlasování, závěrečné?)] pro výběr nejrozdělenějších."""
    out: dict[str, dict] = {}
    for v in votes:
        final = is_final(v)
        for code, (f, a, b, n) in v["group_counts"].items():
            if code in skip:
                continue
            s = out.setdefault(code, _blank())
            for key in ("attendance",) + (("attendance_main",) if final else ()):
                s[key][0] += f + a + b
                s[key][1] += f + a + b + n
            if f + a >= MIN_VOTERS:
                minority = min(f, a) / (f + a)
                for suffix, on in (("", True), ("_main", final)):
                    if on:
                        s["majority" + suffix][0] += max(f, a)
                        s["majority" + suffix][1] += f + a
                        s["considered" + suffix] += 1
                        s["splits" + suffix] += minority >= STRONG_SPLIT
                if minority >= STRONG_SPLIT:
                    s["_split_rows"].append((minority, v["id"], final))
    for s in out.values():
        rows = sorted(s["_split_rows"], key=lambda r: (-r[0], -r[1]))
        s["split_ids"] = [vid for _, vid, _ in rows[:SPLIT_LIMIT]]
        s["split_ids_main"] = [vid for _, vid, fin in rows if fin][:SPLIT_LIMIT]
        del s["_split_rows"]
    return out
