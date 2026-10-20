"""Spočítá statistiky českých poslanců z data/meps.json a data/votes/*.json.

Výstup:
  data/stats.json    metriky na poslance, celkem i po měsících (vždy jako počty x z y)
  data/groups.json   frakce (kód HowTheyVote, kód EP, názvy, barva, logo)
  data/parties.json  české strany (ID organizace v EP, zkratka, název, barva, logo)
  data/own_work.json vlastní práce poslanců (zprávy, stínové zprávy, usnesení, otázky) s výsledky;
                     jen pokud existuje data/proposals.json (fetch_proposals.py)

Ruční údaje (barvy, případně cesty k logům) jsou v data/manual/colors.json. Skript je
jen načte a přimíchá, soubor nikdy nepřepisuje.

Všechny metriky jsou čisté deterministické funkce bez odhadů. Definice jsou v DEFINITIONS
a ukládají se i do stats.json, aby je web mohl zobrazit.

Použití:
    python scripts/compute_stats.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from vote_kinds import is_final, kind_of

POSITIONS = ["FOR", "AGAINST", "ABSTENTION", "DID_NOT_VOTE"]
VOTED = {"FOR", "AGAINST", "ABSTENTION"}
NO_GROUP = {None, "NI"}  # nezařazení nejsou frakce, loajalita se nepočítá
RESULTS_DECIDED = {"ADOPTED", "REJECTED"}  # LAPSED, WITHDRAWN a chybějící výsledek se do souladu nepočítají
CLOSE_MARGIN = 21  # těsné hlasování: |pro − proti| <= 21 (počet českých křesel)
STRONG_SPLIT = 0.3  # výrazné rozdělení mezi Čechy: menšina tvoří aspoň 30 % hlasů pro a proti
TOP_TOPICS = 10
RECENT = 10
INDEPENDENT = "Independent"  # EP tak označuje poslance bez strany; nejde o stranu

DEFINITIONS = {
    "attendance": "Účast na hlasování: v kolika jmenovitých hlasováních v době mandátu poslanec hlasoval (pro, proti nebo "
    "se zdržel). Nejde o prezenční docházku. Poslanec mohl být na jednání a nehlasovat, nebo chybět z důvodů, "
    "které data neuvádějí (nemoc, rodičovská, služební cesta).",
    "attendance_main": "Účast na hlasování jen u závěrečných hlasování: o celém textu, o prozatímní dohodě s Radou nebo o námitce "
    "proti aktu Komise. "
    "Nepočítají se návrhy na zamítnutí, mandáty k jednání s Radou ani žádosti o naléhavý postup.",
    "vote_kind": "Typ hlasování určují pevná pravidla podle popisu hlasování v datech HowTheyVote (scripts/vote_kinds.py): "
    "závěrečné hlasování, prozatímní dohoda s Radou, námitka proti aktu Komise (hlas PRO = vznést námitku), "
    "návrh na zamítnutí (hlas PRO = text zamítnout), mandát k jednání, naléhavý postup, pozměňovací návrh, "
    "dílčí hlasování o části textu, procedurální hlasování, ostatní.",
    "group_loyalty": "Hlasuje s frakcí: v kolika procentech hlasování hlasoval stejně jako většina jeho frakce (k datu "
    "hlasování). Vysoké ani nízké číslo samo o sobě není dobré ani špatné. Odchylky často vycházejí z "
    "postoje domácí strany nebo z národních zájmů. Počítá se jen tam, kde hlasoval a frakce měla "
    "jednoznačnou většinu (pro / proti / zdržet se). Nezařazení (NI) se nepočítají.",
    "cz_agreement": "Podíl hlasování, kde poslanec hlasoval stejně jako většina ostatních českých poslanců, kteří hlasovali. "
    "Bez hlasování s nerozhodnou většinou.",
    "pairwise": "Shoda dvou poslanců: podíl hlasování, kde oba hlasovali a hlasovali stejně.",
    "outcome_agreement": "Soulad s výsledkem: podíl hlasování, kde poslanec hlasoval pro a návrh byl přijat, nebo hlasoval "
    "proti a návrh byl zamítnut. Počítají se jen hlasy pro a proti (zdržení a nehlasování ne) a jen "
    "hlasování s výsledkem přijato / zamítnuto (bez propadlých, stažených a bez výsledku). "
    "Číslo hlavně odráží velikost a pozici frakce: poslanci velkých frakcí, které tvoří většinu, "
    "mají soulad vysoký, poslanci menších a opozičních frakcí nižší. Hlasovat proti většině je "
    "legitimní opoziční role, nízké číslo neznamená horší práci.",
    "group_outcome_agreement": "Průměr frakce: soulad s výsledkem všech poslanců jeho frakce (z celého EP, včetně něj) "
    "ve stejných hlasováních, ve kterých se počítá jemu.",
    "close_votes": f"Těsné hlasování: rozdíl mezi hlasy pro a proti je nejvýš {CLOSE_MARGIN} (tolik křesel má ČR).",
    "decisive_votes": "Těsná hlasování, kde rozhodly české hlasy: těsné hlasování, které by bez hlasů pro a proti českých poslanců dopadlo "
    "opačně (prostá většina, při rovnosti zamítnuto). Vynechávají se hlasování, jejichž oficiální "
    "výsledek neodpovídá prosté většině (vyžadovala jinou většinu), protože u nich nelze kontrafakt "
    "spolehlivě spočítat.",
    "delegations": "Srovnání s delegacemi podobné velikosti: stejná čísla jako u české delegace (jednotnost, těsná hlasování, "
    "která by bez hlasů delegace dopadla opačně) spočítaná stejnými pravidly pro delegace států s 20–22 "
    "poslanci (podle počtu poslanců u posledního hlasování v datech). Kontrafakt „bez hlasů delegace by "
    "hlasování dopadlo opačně“ platí pro jakoukoli skupinu poslanců, jejíž čistý rozdíl pro/proti převýší "
    "celkový rozdíl, takže nic neříká o větším vlivu české delegace. U ostatních států se berou všichni "
    "poslanci, které HowTheyVote u hlasování vede (mandáty z EP API máme jen pro české poslance).",
    "presence": "Docházka na zasedání (podle EP): v kolika dnech jednání v plénu v době mandátu byl poslanec zapsán v prezenční listině EP "
    "(EP Open Data, meetings). Počítají se jen dny, ke kterým listina už existuje (budoucí dny se nepočítají jako neúčast). "
    "Kdo je v listině i mezi omluvenými, je přítomen; omluvení se ukazují zvlášť. Je to jiná metrika než Účast na hlasování, "
    "která počítá hlasy z HowTheyVote: poslanec mohl být na jednání a nehlasovat, nebo se hlasování nezúčastnit z jiných důvodů. "
    "Bez mediánu EP a bez pořadí.",
    "speeches": "Projevy v plénu: počet ústních projevů v rozpravách v době mandátu podle EP Open Data (endpoint speeches) a jejich "
    "celková délka z časových značek zdroje (jen u projevů, kde jsou obě značky). Písemná prohlášení se počítají zvlášť a "
    "do projevů se nesčítají, protože se dají psát hromadně. Jde o počet a čas, ne o kvalitu ani vliv; do třetin v "
    "delegaci nevstupuje a medián EP se neuvádí (projevy všech poslanců EP by znamenaly tisíce dotazů týdně). "
    "Pozměňovací návrhy ve výborech tu nejsou: strojově čitelná data (Parltrack) jsou naposledy z února 2026.",
    "against_group": "Kde hlasoval jinak než frakce: poslanec hlasoval (pro / proti / zdržel se) jinak, než jednoznačná "
    "většina jeho frakce k datu hlasování. U každého takového hlasování se zjišťuje, jak hlasovala většina "
    "jeho české strany (ostatní poslanci strany, kteří k datu hlasování měli mandát a hlasovali). Když strana "
    "nemá jiného hlasujícího poslance nebo je většina nerozhodná, údaj není (null) a nepočítá se. Častá shoda "
    "se stranou při odchylce od frakce znamená, že poslanec sleduje linii domácí strany.",
    "cz_split": "Míra rozdělení mezi Čechy: menší ze dvou čísel (pro, proti) mezi českými poslanci v mandátu, děleno "
    "součtem pro a proti. 0 = všichni na jedné straně, 0,5 = půl na půl. Zdržení a nehlasování se "
    "nepočítají. Při stejné míře rozhoduje větší počet hlasujících.",
    "cz_unity": "Češi jednotně: podíl hlasování, ve kterých všichni čeští poslanci, kteří hlasovali pro nebo proti, "
    "byli na stejné straně (počítají se jen hlasování, kde pro nebo proti hlasovali aspoň dva). "
    f"Výrazné rozdělení: menšina tvoří aspoň {int(STRONG_SPLIT * 100)} % hlasů pro a proti.",
    "party_cohesion": "Jednotnost strany: podíl hlasování, kde aspoň dva poslanci strany hlasovali a všichni hlasovali "
    "stejně (pro / proti / zdržel se). Příslušnost ke straně k datu hlasování.",
    "own_work": "Práce na textech: zprávy (poslanec je zpravodaj), stínové zprávy, stanoviska výborů, návrhy usnesení "
    "(poslanec je signatář) a otázky Komisi a Radě podle EP Open Data. U zpráv a usnesení se ukazuje "
    "výsledek posledního hlavního hlasování o textu v plénu (HowTheyVote), vždy po typech zvlášť. "
    "Samostatný návrh usnesení, který nahradil společný návrh, se počítá jako „nahrazený“, ne jako "
    "zamítnutý. Kde HowTheyVote nemá jmenovité hlasování (ještě neproběhlo, nebo se hlasovalo "
    "zvednutím ruky či tajně), ukazuje se „bez jmenovitého hlasování“. Stanoviska výborů výsledek nemají. Pozměňovací návrhy nejsou zahrnuté: v plénu je zdroje "
    "neuvádějí podle jmen, ve výborech nejsou dostupná aktuální data. Jedna role v jedné proceduře se "
    "počítá jednou.",
    "work_profile": "Profil práce na textech (stránka Práce na textech) počítá přidělené role bez ohledu na výsledek "
    "hlasování: zprávy a stanoviska, které poslanec vede jako zpravodaj, a zprávy a stanoviska, které "
    "vyjednává jako stínový zpravodaj za frakci. U každé kategorie se ukazuje třetina mezi současnými "
    "poslanci delegace (horní třetina = alespoň 2/3 kolegů má méně), nula třetinu nemá. Celkové pořadí "
    "ani body záměrně nepočítáme: zpráva a stanovisko nejsou stejná práce a žádná váha by nebyla "
    "podložená. Podepsané návrhy usnesení se ukazují zvlášť a do třetin nevstupují: podepisují je "
    "desítky poslanců za frakci a společné návrhy sepisují jen některé frakce, takže počet vypovídá "
    "hlavně o frakci. Funkce (předseda či místopředseda výboru, vedení frakce) se uvádějí podle EP "
    "jako kontext a čísla neupravují. Zprávy si frakce rozdělují podle bodů úměrných velikosti, "
    "takže malé frakce a nezařazení jich dostávají méně; ani to se do čísel nepřepočítává. Kdo byl v mandátu méně než "
    "75 % období (od začátku období do posledního hlasování v datech), třetinu nedostane: srovnání počtů s kolegy, kteří mají "
    "za sebou celé období, by vyznělo jako verdikt. Čísla zůstávají.",
    "topics": "Témata podle Legislativní observatoře EP (OEIL, úroveň 2) z HowTheyVote. České názvy jsou ruční překlad "
    "(data/manual/topics_cs.json), OEIL je jen anglicky a francouzsky. Jedno hlasování "
    "může patřit do více témat. Ukazuje se deset témat s nejvíce hlasováními v celém období.",
}


class FormatError(RuntimeError):
    """Vstupní data nemají očekávaný formát."""


def require(obj, keys, where):
    missing = [k for k in keys if not isinstance(obj, dict) or k not in obj]
    if missing:
        raise FormatError(f"{where}: chybí pole {missing}")


def in_mandate(mandates: list[dict], date: str) -> bool:
    return any(m["start"] <= date and (m["end"] is None or date <= m["end"]) for m in mandates)


def majority(counts: dict[str, int]) -> str | None:
    """Jednoznačně nejčastější z pro / proti / zdržet se; při remíze nebo bez hlasů None."""
    best = max((counts.get(p, 0) for p in VOTED), default=0)
    if best == 0:
        return None
    winners = [p for p in VOTED if counts.get(p, 0) == best]
    return winners[0] if len(winners) == 1 else None


def group_majority(group_counts: dict[str, list[int]], group: str | None) -> str | None:
    if group in NO_GROUP or group not in group_counts:
        return None
    row = group_counts[group]
    return majority(dict(zip(POSITIONS, row, strict=False)))


def decided(vote: dict) -> bool:
    return vote.get("result") in RESULTS_DECIDED


def simple_result(n_for: int, n_against: int) -> str:
    return "ADOPTED" if n_for > n_against else "REJECTED"


def is_close(vote: dict) -> bool:
    c = vote["counts"]
    return decided(vote) and abs(c["for"] - c["against"]) <= CLOSE_MARGIN


def decisive_alternative(vote: dict, active: list[dict]) -> str | None:
    """Výsledek bez hlasů pro/proti českých poslanců, pokud by byl opačný; jinak None.
    Jen pro těsná hlasování, jejichž oficiální výsledek odpovídá prosté většině."""
    if not is_close(vote):
        return None
    c = vote["counts"]
    if simple_result(c["for"], c["against"]) != vote["result"]:
        return None
    cz_for = sum(p["position"] == "FOR" for p in active)
    cz_against = sum(p["position"] == "AGAINST" for p in active)
    alt = simple_result(c["for"] - cz_for, c["against"] - cz_against)
    return alt if alt != vote["result"] else None


def cz_split(active: list[dict]) -> tuple[float, int, int] | None:
    """(míra rozdělení, pro, proti) mezi Čechy; None, pokud nejsou na obou stranách."""
    n_for = sum(p["position"] == "FOR" for p in active)
    n_against = sum(p["position"] == "AGAINST" for p in active)
    if not n_for or not n_against:
        return None
    return min(n_for, n_against) / (n_for + n_against), n_for, n_against


def topic_codes(vote: dict) -> set[str]:
    """Témata OEIL zkrácená na úroveň 2 (např. 3.70.03 -> 3.70)."""
    return {".".join(t["code"].split(".")[:2]) for t in (vote.get("topics") or {}).get("oeil", [])}


def top_topics(votes: list[dict], n: int = TOP_TOPICS) -> list[str]:
    c = Counter(code for v in votes for code in topic_codes(v))
    return [code for code, _ in sorted(c.items(), key=lambda x: (-x[1], x[0]))[:n]]


def empty_metrics() -> dict:
    return {
        "attendance": [0, 0],
        "attendance_main": [0, 0],
        "group_loyalty": [0, 0],
        "group_loyalty_main": [0, 0],
        "cz_agreement": [0, 0],
        "outcome": [0, 0],
        "outcome_main": [0, 0],
        "outcome_close": [0, 0],
        "group_outcome": [0, 0],
        "group_outcome_main": [0, 0],
        "positions": {p: 0 for p in POSITIONS},
    }


def add_vote(metrics: dict, vote: dict, pos: dict, others: list[str]) -> None:
    """Započte jedno hlasování jednoho poslance. others = pozice ostatních Čechů v mandátu."""
    position = pos["position"]
    voted = position in VOTED
    metrics["positions"][position] += 1
    metrics["attendance"][1] += 1
    metrics["attendance"][0] += voted
    if is_final(vote):
        metrics["attendance_main"][1] += 1
        metrics["attendance_main"][0] += voted
    if not voted:
        return
    gm = group_majority(vote["group_counts"], pos["group_code"])
    if gm is not None:
        metrics["group_loyalty"][1] += 1
        metrics["group_loyalty"][0] += position == gm
        if is_final(vote):
            metrics["group_loyalty_main"][1] += 1
            metrics["group_loyalty_main"][0] += position == gm
    cm = majority(Counter(p for p in others if p in VOTED))
    if cm is not None:
        metrics["cz_agreement"][1] += 1
        metrics["cz_agreement"][0] += position == cm
    if position == "ABSTENTION" or not decided(vote):
        return
    agree = (position == "FOR") == (vote["result"] == "ADOPTED")
    keys = ["outcome"] + (["outcome_main"] if is_final(vote) else []) + (["outcome_close"] if is_close(vote) else [])
    for k in keys:
        metrics[k][1] += 1
        metrics[k][0] += agree
    group = pos["group_code"]
    if group not in NO_GROUP and group in vote["group_counts"]:
        g_for, g_against = vote["group_counts"][group][:2]
        g_agree = g_for if vote["result"] == "ADOPTED" else g_against
        for k in ["group_outcome"] + (["group_outcome_main"] if is_final(vote) else []):
            metrics[k][1] += g_for + g_against
            metrics[k][0] += g_agree


def active_positions(vote: dict, by_id: dict, unknown: set | None = None) -> list[dict]:
    """Pozice Čechů, kteří byli k datu hlasování v mandátu."""
    active = []
    for p in vote["cz_positions"]:
        m = by_id.get(p["member_id"])
        if m is None:
            if unknown is not None:
                unknown.add(p["member_id"])
            continue
        if in_mandate(m["mandates"], vote["date"]):
            active.append(p)
    return active


def party_majority(pos: dict, active: list[dict]) -> str | None:
    """Jak hlasovala většina české strany poslance (bez něj samotného), k datu hlasování. None: strana nemá jiného hlasujícího
    poslance (jednočlenná strana, ostatní nehlasovali), většina je nerozhodná, nebo poslanec není členem strany (Independent)."""
    party = pos.get("national_party_id")
    if party is None or pos.get("national_party") == INDEPENDENT:
        return None
    mates = [o["position"] for o in active if o is not pos and o.get("national_party_id") == party and o["position"] in VOTED]
    return majority(Counter(mates)) if mates else None


def compute(meps: list[dict], votes: list[dict], topics: list[str] | None = None) -> dict:
    by_id = {m["id"]: m for m in meps}
    topics = top_topics(votes) if topics is None else topics
    topic_set = set(topics)
    total = {i: empty_metrics() for i in by_id}
    monthly: dict[int, dict[str, dict]] = {i: {} for i in by_id}
    by_topic: dict[int, dict[str, dict]] = {i: {t: empty_metrics() for t in topics} for i in by_id}
    pairwise: dict[int, dict[int, list[int]]] = {i: defaultdict(lambda: [0, 0]) for i in by_id}
    against: dict[int, list[dict]] = {i: [] for i in by_id}
    decisive: dict[int, list[dict]] = {i: [] for i in by_id}
    unknown = set()

    for vote in votes:
        require(vote, ["id", "date", "is_main", "group_counts", "cz_positions", "counts"], f"hlasování {vote.get('id')}")
        active = active_positions(vote, by_id, unknown)
        month = vote["date"][:7]
        vote_topics = [t for t in topic_codes(vote) if t in topic_set]
        alt = decisive_alternative(vote, active)
        for p in active:
            i = p["member_id"]
            others = [o["position"] for o in active if o is not p]
            add_vote(total[i], vote, p, others)
            add_vote(monthly[i].setdefault(month, empty_metrics()), vote, p, others)
            for t in vote_topics:
                add_vote(by_topic[i][t], vote, p, others)
            gm = group_majority(vote["group_counts"], p["group_code"])
            if p["position"] in VOTED and gm is not None and p["position"] != gm:
                pm = party_majority(p, active)
                against[i].append(
                    {
                        "id": vote["id"],
                        "is_final": is_final(vote),
                        "position": p["position"],
                        "group_code": p["group_code"],
                        "group_majority": gm,
                        "party_majority": pm,
                    }
                )
            if alt is not None:
                decisive[i].append({"id": vote["id"], "position": p["position"]})
        voted = [p for p in active if p["position"] in VOTED]
        for a in voted:
            for b in voted:
                if a is not b:
                    cell = pairwise[a["member_id"]][b["member_id"]]
                    cell[1] += 1
                    cell[0] += a["position"] == b["position"]

    if unknown:
        raise FormatError(f"hlasování obsahují poslance, kteří nejsou v meps.json: {sorted(unknown)}")
    newest = lambda xs: list(reversed(xs))
    return {
        str(i): {
            "total": total[i],
            "monthly": dict(sorted(monthly[i].items())),
            "pairwise": {str(k): v for k, v in sorted(pairwise[i].items())},
            "topics": by_topic[i],
            "against_group": {
                "count": len(against[i]),
                "count_main": sum(x["is_final"] for x in against[i]),
                # D3: kolikrát z toho hlasoval stejně jako většina jeho české strany (u kolika měla strana jasnou většinu)
                "party_known": sum(x["party_majority"] is not None for x in against[i]),
                "with_party": sum(x["party_majority"] == x["position"] for x in against[i]),
                "party_known_main": sum(x["is_final"] and x["party_majority"] is not None for x in against[i]),
                "with_party_main": sum(x["is_final"] and x["party_majority"] == x["position"] for x in against[i]),
                "recent": newest(against[i])[:RECENT],
                "recent_main": [x for x in newest(against[i]) if x["is_final"]][:RECENT],
            },
            "decisive": newest(decisive[i]),
        }
        for i in sorted(by_id)
    }


def last_session_dates(dates: list[str], max_gap_days: int = 3) -> list[str]:
    """Dny posledního zasedání: od posledního dne zpět, dokud mezera mezi dny nepřesáhne max_gap_days."""
    import datetime as dt

    days = sorted(set(dates))
    if not days:
        return []
    out = [days[-1]]
    for d in reversed(days[:-1]):
        gap = (dt.date.fromisoformat(out[-1]) - dt.date.fromisoformat(d)).days
        if gap > max_gap_days:
            break
        out.append(d)
    return sorted(out)


def analyze_votes(meps: list[dict], votes: list[dict], n_all: int = 100, n_main: int = 50) -> dict:
    """Těsná a rozhodující hlasování a rozkol mezi Čechy (seznamy ID hlasování)."""
    by_id = {m["id"]: m for m in meps}
    close, decisive, splits = [], [], []
    unity = {"united": 0, "considered": 0, "strong_split": 0, "united_final": 0, "considered_final": 0}
    unity_by_date: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for vote in votes:
        active = active_positions(vote, by_id)
        n_for = sum(p["position"] == "FOR" for p in active)
        n_against = sum(p["position"] == "AGAINST" for p in active)
        if n_for + n_against >= 2:
            united = n_for == 0 or n_against == 0
            strong = not united and min(n_for, n_against) / (n_for + n_against) >= STRONG_SPLIT
            unity["considered"] += 1
            unity["united"] += united
            unity["strong_split"] += strong
            if is_final(vote):
                unity["considered_final"] += 1
                unity["united_final"] += united
            d = unity_by_date[vote["date"]]
            d[0] += united
            d[1] += 1
            d[2] += strong
        if is_close(vote):
            close.append({"id": vote["id"], "is_final": is_final(vote)})
        alt = decisive_alternative(vote, active)
        if alt is not None:
            decisive.append({"id": vote["id"], "alternative_result": alt, "is_final": is_final(vote), "vote_kind": kind_of(vote)})
        sp = cz_split(active)
        if sp is not None:
            splits.append(
                {
                    "id": vote["id"],
                    "date": vote["date"],
                    "is_final": is_final(vote),
                    "split": round(sp[0], 4),
                    "for": sp[1],
                    "against": sp[2],
                }
            )
    rank = lambda xs: sorted(xs, key=lambda x: (-x["split"], -(x["for"] + x["against"]), x["date"], x["id"]))
    session = set(last_session_dates([v["date"] for v in votes]))
    session_votes = [v for v in votes if v["date"] in session]
    sess_unity = [sum(unity_by_date[d][i] for d in session) for i in range(3)]
    return {
        "unity": {
            **unity,
            "strong_threshold": STRONG_SPLIT,
            "last_session": {"united": sess_unity[0], "considered": sess_unity[1], "strong_split": sess_unity[2]},
        },
        "close": {"count": len(close), "count_main": sum(x["is_final"] for x in close), "ids": [x["id"] for x in close]},
        "decisive": list(reversed(decisive)),
        "splits": {
            "count": len(splits),
            "count_main": sum(x["is_final"] for x in splits),
            "all": rank(splits)[:n_all],
            "main": rank([x for x in splits if x["is_final"]])[:n_main],
            "last_session": {
                "from": min(session) if session else None,
                "to": max(session) if session else None,
                "votes": len(session_votes),
                "split": rank([x for x in splits if x["date"] in session]),
            },
        },
    }


def independent_ids(meps: list[dict]) -> set[int]:
    return {int(p["org_id"]) for m in meps for p in m["parties"] if p.get("name") == INDEPENDENT}


def compute_parties(meps: list[dict], votes: list[dict]) -> dict:
    """Metriky stran podle příslušnosti k datu hlasování (HowTheyVote), jednotnost a hlasování,
    kde se strana rozdělila (poslanci strany hlasovali pro i proti)."""
    by_id = {m["id"]: m for m in meps}
    skip = independent_ids(meps)
    out: dict[int, dict] = {}
    for vote in votes:
        active = active_positions(vote, by_id)
        by_party: dict[int, list[dict]] = defaultdict(list)
        for p in active:
            if p.get("national_party_id") is not None and p["national_party_id"] not in skip:
                by_party[p["national_party_id"]].append(p)
        for party, members in by_party.items():
            st = out.setdefault(party, {"total": empty_metrics(), "cohesion": [0, 0], "cohesion_main": [0, 0], "splits": []})
            for p in members:
                add_vote(st["total"], vote, p, [o["position"] for o in active if o is not p])
            voted = [p["position"] for p in members if p["position"] in VOTED]
            if len(voted) >= 2:
                same = len(set(voted)) == 1
                for k in ["cohesion"] + (["cohesion_main"] if is_final(vote) else []):
                    st[k][1] += 1
                    st[k][0] += same
            if "FOR" in voted and "AGAINST" in voted:
                st["splits"].append({"id": vote["id"], "is_final": is_final(vote)})
    result = {}
    for party, st in sorted(out.items()):
        splits = list(reversed(st.pop("splits")))
        result[str(party)] = {
            **st,
            "splits": {
                "count": len(splits),
                "count_main": sum(x["is_final"] for x in splits),
                "recent": [x["id"] for x in splits[:20]],
                "recent_main": [x["id"] for x in splits if x["is_final"]][:20],
            },
        }
    return result


def derive_group_codes(meps: list[dict], votes: list[dict]) -> dict[str, str]:
    """Párování kódů frakcí HowTheyVote -> EP podle toho, v jaké frakci poslanec v den hlasování byl
    v obou zdrojích. Bere se jen jednoznačné párování."""
    by_id = {m["id"]: m for m in meps}
    pairs: dict[str, Counter] = defaultdict(Counter)
    for vote in votes:
        for p in vote["cz_positions"]:
            m = by_id.get(p["member_id"])
            if not m or p["group_code"] is None:
                continue
            ep = [g["code"] for g in m["groups"] if g["start"] <= vote["date"] and (g["end"] is None or vote["date"] <= g["end"])]
            if len(ep) == 1:
                pairs[p["group_code"]][ep[0]] += 1
    return {htv: c.most_common(1)[0][0] for htv, c in pairs.items() if len(c) == 1}


def find_logo(assets: Path, kind: str, key: str) -> str | None:
    for ext in ("svg", "png", "jpg", "webp"):
        if (assets / "logos" / kind / f"{key}.{ext}").exists():
            return f"assets/logos/{kind}/{key}.{ext}"
    return None


SVG_TAG_RE = re.compile(r"<svg\b[^>]*>", re.S)
SVG_ATTR_RE = r'\b{}\s*=\s*["\']([^"\']+)["\']'
NUM_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(px)?\s*$")


def logo_aspect(path: Path) -> float | None:
    """Poměr šířka/výška loga (SVG z viewBox, jinak width/height; rastr přes Pillow). Web podle něj
    vyrovná velikost log na stejnou plochu, aby široká slovní loga nepřebíjela čtvercová. Neznámý = None."""
    if not path.exists():
        return None
    try:
        if path.suffix.lower() == ".svg":
            tag = SVG_TAG_RE.search(path.read_text(encoding="utf-8", errors="replace"))
            if not tag:
                return None
            vb = re.search(SVG_ATTR_RE.format("viewBox"), tag.group(0))
            if vb:
                parts = [float(x) for x in re.split(r"[\s,]+", vb.group(1).strip())]
                if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
                    return round(parts[2] / parts[3], 3)
            dims = []
            for attr in ("width", "height"):
                m = re.search(SVG_ATTR_RE.format(attr), tag.group(0))
                n = NUM_RE.match(m.group(1)) if m else None
                dims.append(float(n.group(1)) if n else None)
            if dims[0] and dims[1]:
                return round(dims[0] / dims[1], 3)
            return None
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
        return round(w / h, 3) if w and h else None
    except (OSError, ValueError):
        return None


COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def load_manual(path: Path) -> dict:
    """data/manual/colors.json: {"groups": {kód: {...}}, "parties": {id: {...}}} s poli brand_color (oficiální,
    vždy s brand_source) a chart_color (barva webu kvůli rozlišitelnosti). Chybějící soubor = žádné ruční údaje."""
    if not path.exists():
        return {"groups": {}, "parties": {}}
    manual = json.loads(path.read_text(encoding="utf-8"))
    require(manual, ["groups", "parties"], str(path))
    for kind in ("groups", "parties"):
        for key, entry in manual[kind].items():
            if not isinstance(entry, dict):
                raise FormatError(f"{path}: {kind}.{key} musí být objekt")
            for field in ("brand_color", "chart_color", "color"):
                color = entry.get(field)
                if color is not None and not COLOR_RE.match(color):
                    raise FormatError(f"{path}: {kind}.{key}.{field} '{color}' není ve tvaru #RRGGBB")
            if entry.get("brand_color") and not entry.get("brand_source"):
                raise FormatError(f"{path}: {kind}.{key}.brand_color nemá brand_source (odkud barva je)")
    return manual


def load_logos(path: Path, public: Path) -> dict:
    """data/manual/logos.json: {"groups": {kód: {"file", "source", ...}}, "parties": {id: {...}}}.
    Použije se jen záznam se souborem, který v public/ existuje a má uvedený zdroj."""
    if not path.exists():
        return {"groups": {}, "parties": {}}
    doc = json.loads(path.read_text(encoding="utf-8"))
    require(doc, ["groups", "parties"], str(path))
    out = {"groups": {}, "parties": {}}
    for kind in ("groups", "parties"):
        for key, entry in doc[kind].items():
            f = entry.get("file")
            if not f:
                continue
            if not (public / f).exists():
                raise FormatError(f"{path}: {kind}.{key}.file '{f}' v public/ neexistuje")
            if not entry.get("source"):
                raise FormatError(f"{path}: {kind}.{key} má logo bez zdroje (source)")
            out[kind][key] = {"logo": f, "logo_source": entry["source"]}
    return out


def identity(manual: dict, logos: dict, key: str, assets: Path, kind_dir: str) -> dict:
    """Barvy a logo strany nebo frakce: oficiální barva má přednost, jinak barva webu."""
    m = manual.get(key, {})
    brand = m.get("brand_color")
    chart = m.get("chart_color") or m.get("color")
    lg = logos.get(key) or {}
    logo = lg.get("logo") or m.get("logo") or find_logo(assets, kind_dir, key)
    return {
        "color": brand or chart,
        "brand_color": brand,
        "chart_color": chart or brand,
        "logo": logo,
        "logo_source": lg.get("logo_source"),
        "logo_aspect": logo_aspect(assets.parent / logo) if logo else None,
    }


def build_groups(
    index_groups: list[dict],
    meps: list[dict],
    votes: list[dict],
    assets: Path,
    manual: dict | None = None,
    logos: dict | None = None,
    labels_path: Path | None = None,
) -> list[dict]:
    manual = (manual or {}).get("groups", {})
    logos = (logos or {}).get("groups", {})
    mapping = derive_group_codes(meps, votes)
    names_cs = {g["code"]: g["name_cs"] for m in meps for g in m["groups"]}
    from overrides import load_group_labels  # noqa: PLC0415 (overrides importuje compute_stats)

    glabels = load_group_labels(labels_path) if labels_path else {}
    out = []
    for g in index_groups:
        ep_code = mapping.get(g["code"])
        out.append(
            {
                "code": g["code"],
                "ep_code": ep_code,
                "short_label": glabels.get(g["code"], g["short_label"]),
                "short_label_ep": g["short_label"],
                "label": g["label"],
                "name_cs": names_cs.get(ep_code),
                **identity(manual, logos, g["code"], assets, "ep"),
            }
        )
    return out


def build_parties(meps: list[dict], assets: Path, manual: dict | None = None, logos: dict | None = None) -> list[dict]:
    manual = (manual or {}).get("parties", {})
    logos = (logos or {}).get("parties", {})
    parties = {}
    for m in meps:
        for p in m["parties"]:
            parties[p["org_id"]] = {
                "id": int(p["org_id"]),
                "short_label": p["short_label"],
                "short_label_ep": p.get("short_label_ep", p["short_label"]),
                "name": p["name"],
                "independent": p["name"] == INDEPENDENT,
                **identity(manual, logos, p["org_id"], assets, "cz"),
            }
    return [parties[k] for k in sorted(parties, key=int)]


SEED_TITLES = "procedure_titles_cs.json"


def procedure_titles(data_dir: Path) -> dict[str, str]:
    """{číslo procedury (2023/0436(COD)): oficiální český název} z EP Open Data API, jak je stáhl fetch_proposals.py
    (proposals_state.json u všech procedur, proposals.json u procedur s českou účastí). Bez souborů prázdný slovník."""
    out: dict[str, str] = {}
    items_path, state_path = data_dir / "proposals.json", data_dir / "proposals_state.json"
    if items_path.exists():
        for i in json.loads(items_path.read_text(encoding="utf-8")).get("items", []):
            cs = (i.get("title") or {}).get("cs")
            if i.get("kind") == "procedure" and i.get("label") and cs:
                out[i["label"]] = cs
    seed_path = data_dir / SEED_TITLES
    if seed_path.exists():  # jednorázově stažené názvy (stejný dotaz jako fetch_proposals), než je doplní denní běh
        for meta in json.loads(seed_path.read_text(encoding="utf-8")).get("titles", {}).values():
            if meta.get("label") and meta.get("title_cs"):
                out[meta["label"]] = meta["title_cs"]
    if state_path.exists():
        for meta in json.loads(state_path.read_text(encoding="utf-8")).get("procedures", {}).values():
            labels = meta.get("label")
            for label in labels if isinstance(labels, list) else [labels]:
                if label and meta.get("title_cs"):
                    out[label] = meta["title_cs"]
    return out


def apply_titles(votes: list[dict], titles: dict[str, str]) -> None:
    """Doplní k hlasování title_cs: oficiální český název procedury, o kterou jde (HowTheyVote má jen angličtinu)."""
    for v in votes:
        cs = titles.get((v.get("procedure") or {}).get("reference") or "")
        if cs:
            v["title_cs"] = cs


def load_votes(votes_dir: Path) -> tuple[dict, list[dict]]:
    index_path = votes_dir / "index.json"
    if not index_path.exists():
        raise FormatError(f"chybí {index_path}, spusť nejdřív fetch_votes.py")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    require(index, ["months", "groups", "source"], "votes/index.json")
    votes = []
    for m in index["months"]:
        data = json.loads((votes_dir / f"{m['month']}.json").read_text(encoding="utf-8"))
        require(data, ["votes"], f"votes/{m['month']}.json")
        votes.extend(data["votes"])
    apply_titles(votes, procedure_titles(votes_dir.parent))
    # přijatý text podle EP Open Data (adopted_texts.py) má přednost před polem z HowTheyVote
    from adopted_texts import apply as apply_adopted

    apply_adopted(votes, votes_dir.parent)
    return index, votes


def build_own_work(data_dir: Path, votes: list[dict]) -> dict | None:
    import own_work

    proposals_path, state_path = data_dir / "proposals.json", data_dir / "proposals_state.json"
    if not proposals_path.exists() or not state_path.exists():
        return None
    proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    require(proposals, ["items", "source"], "proposals.json")
    require(state, ["documents"], "proposals_state.json")
    linked = own_work.link(proposals["items"], state["documents"], votes)
    passed = {str(k): own_work.passed(v) for k, v in linked.items()}
    # Pořadí jen v současné delegaci: poslanci v mandátu k datu posledního hlasování v datech (reprodukovatelné).
    ref = max((v["date"] for v in votes), default=None)
    meps_path = data_dir / "meps.json"
    members = None
    if ref and meps_path.exists():
        meps = json.loads(meps_path.read_text(encoding="utf-8"))["meps"]
        members = {
            str(m["id"]): min(x["start"] for x in m["mandates"])
            for m in meps
            if any(x["start"] <= ref and (x["end"] is None or ref <= x["end"]) for x in m["mandates"])
        }
    roles = {str(k): own_work.roles(v) for k, v in linked.items()}
    profile = own_work.delegation_profile(roles, members, until=ref)
    return {
        "source": proposals["source"],
        "updated": state.get("updated"),
        "complete": state.get("complete", False),
        "type_labels": own_work.TYPE_LABELS,
        "meps": {
            str(k): {
                "summary": own_work.summarize(v),
                "passed": passed[str(k)],
                "roles": {**roles[str(k)], "delegation": profile.get(str(k))},
                "items": v,
            }
            for k, v in sorted(linked.items())
        },
    }


def run(data_dir: Path, assets: Path) -> dict:
    meps_doc = json.loads((data_dir / "meps.json").read_text(encoding="utf-8"))
    require(meps_doc, ["meps", "source"], "meps.json")
    for m in meps_doc["meps"]:
        require(m, ["id", "mandates", "groups", "parties"], f"meps.json poslanec {m.get('id')}")
    index, votes = load_votes(data_dir / "votes")
    meps = meps_doc["meps"]
    from overrides import apply_party_labels  # noqa: PLC0415 (overrides importuje compute_stats)

    apply_party_labels(meps, data_dir / "manual" / "party_labels.json")
    topics = top_topics(votes)
    stats = {
        "sources": {"votes": index["source"], "meps": meps_doc["source"]},
        "period": {"from": min(v["date"] for v in votes), "to": max(v["date"] for v in votes)} if votes else None,
        "votes_total": len(votes),
        "definitions": DEFINITIONS,
        "meps": compute(meps, votes, topics),
        "parties": compute_parties(meps, votes),
        "votes_analysis": analyze_votes(meps, votes),
        "topics": [
            {"code": t, "label": index.get("oeil_subjects", {}).get(t), "votes": sum(t in topic_codes(v) for v in votes)} for t in topics
        ],
    }
    write = lambda name, obj: (data_dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write("stats.json", stats)
    own = build_own_work(data_dir, votes)
    if own is not None:
        write("own_work.json", own)
    manual = load_manual(data_dir / "manual" / "colors.json")
    logos = load_logos(data_dir / "manual" / "logos.json", assets.parent)
    write("groups.json", build_groups(index["groups"], meps, votes, assets, manual, logos, data_dir / "manual" / "group_labels.json"))
    write("parties.json", build_parties(meps, assets, manual, logos))
    return stats


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=root / "data")
    p.add_argument("--assets", type=Path, default=root / "public" / "assets")
    args = p.parse_args(argv)
    try:
        stats = run(args.data_dir, args.assets)
    except FormatError as e:
        print(f"CHYBA FORMÁTU: {e}", file=sys.stderr)
        return 2
    print(f"statistiky pro {len(stats['meps'])} poslanců z {stats['votes_total']} hlasování", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
