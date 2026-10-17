"""Vlastní práce poslanců: položky z data/proposals.json spojené s výsledky hlasování z HowTheyVote.

Čisté funkce bez síťových dotazů; volá je compute_stats.py.

Typy (TYPE_LABELS) a stavy (STATUS):
  ADOPTED / REJECTED / LAPSED / WITHDRAWN  výsledek posledního závěrečného hlasování o textu (celý text nebo
               prozatímní dohoda). Když o textu žádné takové není a Parlament přijal návrh na zamítnutí, je text
               zamítnutý (REJECTED, note = "rejection_adopted"). Mandáty a naléhavé postupy se nepočítají.
  superseded   samostatný návrh usnesení nahradil společný návrh (o tom se hlasovalo)
  no_vote      v datech HowTheyVote k textu není hlavní jmenovité hlasování (ještě neproběhlo, nebo se
               hlasovalo jinak než jmenovitě, např. tajně u jmenování)
  answered / unanswered   otázky: zda přišla odpověď
  None         výsledek se nesleduje (stanoviska výborů)
Výsledek se počítá jen tam, kde je známý, vždy po typech zvlášť.
"""

from __future__ import annotations

from vote_kinds import is_final, kind_of

TYPE_LABELS = {
    "report": "Zprávy (zpravodaj/ka)",
    "shadow_report": "Stínové zprávy",
    "opinion": "Stanoviska výborů (zpravodaj/ka)",
    "shadow_opinion": "Stínová stanoviska",
    "motion": "Návrhy usnesení",
    "joint_motion": "Společné návrhy usnesení",
    "question": "Otázky Komisi a Radě",
}
VOTED = {"ADOPTED", "REJECTED"}
# Typ procedury z Legislativní observatoře (OEIL). Legislativní = Parlament spolurozhoduje o právním předpisu.
LEGISLATIVE = {"COD", "CNS", "APP"}
LEAD_ROLES = {"RAPPORTEUR", "RAPPORTEUR_CO"}


def htv_reference(doc_id: str, label: str | None) -> str | None:
    """Reference hlasování v HowTheyVote: A10-0142/2025, B10-0156/2025, RC-B10-0156/2025."""
    if doc_id.startswith("RC-"):
        parts = doc_id.split("-")  # RC-10-2025-0156
        return f"RC-B{parts[1]}-{parts[3]}/{parts[2]}" if len(parts) == 4 else None
    return label


def main_votes_by_reference(votes: list[dict]) -> dict[str, list[dict]]:
    """Závěrečná hlasování a návrhy na zamítnutí podle reference textu, seřazená podle času."""
    out: dict[str, list[dict]] = {}
    for v in votes:
        if v.get("reference") and (is_final(v) or kind_of(v) == "rejection"):
            out.setdefault(v["reference"], []).append(v)
    for lst in out.values():
        lst.sort(key=lambda v: (v.get("timestamp") or v["date"], v["id"]))
    return out


def vote_status(reference: str | None, by_ref: dict) -> tuple[str, int | None, str | None]:
    """(stav, ID hlasování, datum) podle posledního závěrečného hlasování o textu; bez něj podle
    přijatého návrhu na zamítnutí (text zamítnut)."""
    lst = by_ref.get(reference) if reference else None
    if not lst:
        return "no_vote", None, None
    finals = [v for v in lst if is_final(v)]
    if finals:
        last = finals[-1]
        return (last.get("result") or "no_vote"), last["id"], last["date"]
    rejections = [v for v in lst if kind_of(v) == "rejection" and v.get("result") == "ADOPTED"]
    if rejections:
        last = rejections[-1]
        return "REJECTED", last["id"], last["date"]
    return "no_vote", None, None


def link(proposals: list[dict], documents: dict, votes: list[dict]) -> dict[int, list[dict]]:
    """Vrací {mep_id: [položky vlastní práce s typem, rolí a stavem]}."""
    by_ref = main_votes_by_reference(votes)
    rejection_ids = {v["id"] for lst in by_ref.values() for v in lst if kind_of(v) == "rejection"}
    note = lambda vote_id: {"note": "rejection_adopted"} if vote_id in rejection_ids else {}
    reports_by_proc: dict[str, list[tuple[str, dict]]] = {}
    superseded_by: dict[str, str] = {}
    for doc_id, meta in documents.items():
        if meta.get("kind") == "report" and meta.get("procedure"):
            reports_by_proc.setdefault(meta["procedure"], []).append((doc_id, meta))
        if meta.get("kind") == "joint_motion":
            for b in meta.get("derived_from") or []:
                superseded_by[b] = doc_id

    def report_status(proc: str | None):
        """Stav zprávy z procedury: poslední zpráva, ke které existuje hlavní hlasování."""
        best = ("no_vote", None, None, None)
        for doc_id, meta in sorted(reports_by_proc.get(proc, []), key=lambda x: x[1].get("date") or ""):
            st = vote_status(htv_reference(doc_id, meta.get("label")), by_ref)
            if st[0] != "no_vote" or best[3] is None:
                best = (*st, meta.get("label"))
        return best

    process_types = {i["procedure"]: i.get("process_type") for i in proposals if i["kind"] == "procedure" and i.get("procedure")}

    def ptype(procedure: str | None) -> dict:
        t = process_types.get(procedure) if procedure else None
        return {"process_type": t, "legislative": (t in LEGISLATIVE) if t else None}

    out: dict[int, list[dict]] = {}

    def add(mep_id, entry):
        out.setdefault(mep_id, []).append(entry)

    # Procedury, u kterých má poslanec zprávu jako dokument. Spočítat předem, protože pořadí položek v datech
    # není zaručené (procedura může přijít dřív než dokument zprávy a zpráva by se započetla dvakrát).
    report_procs: dict[int, set] = {}
    for item in proposals:
        if item["kind"] == "report":
            for p in item["participants"]:
                report_procs.setdefault(p["mep_id"], set()).add(item.get("procedure"))
    # Jedna role v jedné proceduře = jedna položka. EP někdy uvádí stejnou roli vícekrát (jiné datum, bez výboru),
    # z dat ale nejde poznat, jestli jde o různé výbory, takže se počítá jednou.
    seen_roles: set[tuple] = set()
    for item in proposals:
        base = {"id": item["id"], "label": item.get("label"), "date": item.get("date"), "title": item.get("title"), "url": item.get("url")}
        kind = item["kind"]
        if kind in ("report", "motion", "joint_motion"):
            status, vote_id, vote_date = vote_status(htv_reference(item["id"], item.get("label")), by_ref)
            extra = {}
            if kind == "motion" and status == "no_vote" and item["id"] in superseded_by:
                rc = superseded_by[item["id"]]
                rc_status, rc_vote, _ = vote_status(htv_reference(rc, None), by_ref)
                if rc_status != "no_vote":
                    status, extra = "superseded", {"joint_motion": rc, "joint_result": rc_status, "joint_vote_id": rc_vote}
            for p in item["participants"]:
                add(
                    p["mep_id"],
                    {
                        **base,
                        "type": kind,
                        "role": p["role"],
                        "status": status,
                        "vote_id": vote_id,
                        "vote_date": vote_date,
                        "signatories_total": item.get("signatories_total"),
                        **(ptype(item.get("procedure")) if kind == "report" else {}),
                        **note(vote_id),
                        **extra,
                    },
                )
        elif kind == "procedure":
            for p in item["participants"]:
                role = p["role"]
                if role in ("RAPPORTEUR", "RAPPORTEUR_CO"):
                    if item["procedure"] in report_procs.get(p["mep_id"], set()):
                        continue  # zpráva už je započtená z dokumentu
                    typ = "report"
                elif role == "RAPPORTEUR_SHADOW":
                    typ = "shadow_report"
                elif role == "RAPPORTEUR_OPINION":
                    typ = "opinion"
                elif role == "RAPPORTEUR_SHADOW_OPINION":
                    typ = "shadow_opinion"
                else:
                    continue
                if (p["mep_id"], typ, item["procedure"]) in seen_roles:
                    continue
                seen_roles.add((p["mep_id"], typ, item["procedure"]))
                if typ in ("report", "shadow_report"):
                    status, vote_id, vote_date, report_label = report_status(item["procedure"])
                else:
                    status, vote_id, vote_date, report_label = None, None, None, None
                add(
                    p["mep_id"],
                    {
                        **base,
                        "date": p.get("date") or item.get("date"),
                        "type": typ,
                        "role": role,
                        "group": p.get("group"),
                        "committee": p.get("in_name_of"),
                        "status": status,
                        "vote_id": vote_id,
                        "vote_date": vote_date,
                        "report": report_label,
                        **ptype(item.get("procedure")),
                        **note(vote_id),
                    },
                )
        elif kind.startswith("question"):
            for p in item["participants"]:
                add(
                    p["mep_id"],
                    {
                        **base,
                        "type": "question",
                        "subtype": kind,
                        "role": p["role"],
                        "status": "answered" if item.get("answer_date") else "unanswered",
                        "answer_date": item.get("answer_date"),
                        "authors_total": item.get("authors_total"),
                    },
                )
    for lst in out.values():
        lst.sort(key=lambda e: (e.get("date") or "", e["id"]), reverse=True)
    return out


def summarize(entries: list[dict]) -> dict[str, dict]:
    """Souhrn po typech: počet, a kde je výsledek známý, kolik bylo hlasováno a přijato."""
    out = {}
    for typ in TYPE_LABELS:
        lst = [e for e in entries if e["type"] == typ]
        s = {"count": len(lst)}
        if typ == "question":
            s["answered"] = sum(e["status"] == "answered" for e in lst)
        elif typ in ("report", "shadow_report", "motion", "joint_motion"):
            s["voted"] = sum(e["status"] in VOTED for e in lst)
            s["adopted"] = sum(e["status"] == "ADOPTED" for e in lst)
            s["no_vote"] = sum(e["status"] == "no_vote" for e in lst)
            s["other"] = sum(e["status"] in ("LAPSED", "WITHDRAWN") for e in lst)
            if typ == "motion":
                s["superseded"] = sum(e["status"] == "superseded" for e in lst)
        out[typ] = s
    return out


def passed(entries: list[dict]) -> dict:
    """Co z práce poslance prošlo: přijaté zprávy, kde byl zpravodaj (vedl text), a kde byl stínový zpravodaj
    (vyjednával za svou frakci), zvlášť legislativní; přijatá usnesení, která podepsal; zprávy zatím bez
    jmenovitého hlasování. Jen počty z dat, žádné váhy ani body."""

    def count(pred):
        return sum(1 for e in entries if pred(e))

    lead = lambda e: e["type"] == "report"
    shadow = lambda e: e["type"] == "shadow_report"
    adopted = lambda e: e.get("status") == "ADOPTED"
    return {
        "lead_adopted": count(lambda e: lead(e) and adopted(e)),
        "lead_adopted_legislative": count(lambda e: lead(e) and adopted(e) and e.get("legislative")),
        "lead_pending": count(lambda e: lead(e) and e.get("status") == "no_vote"),
        "shadow_adopted": count(lambda e: shadow(e) and adopted(e)),
        "shadow_adopted_legislative": count(lambda e: shadow(e) and adopted(e) and e.get("legislative")),
        "shadow_pending": count(lambda e: shadow(e) and e.get("status") == "no_vote"),
        "resolutions_adopted": count(lambda e: e["type"] in ("motion", "joint_motion") and adopted(e)),
    }


# Přidělené role (práce), ne výsledek hlasování: kategorie profilu na stránce „Vlastní práce“.
# Klíč → typy položek z link(). Usnesení se počítají zvlášť a do třetin nevstupují (spolupodpis desítek
# poslanců za frakci; společné návrhy navíc sepisují jen některé frakce).
ROLE_TYPES = {
    "lead_reports": ("report",),
    "lead_opinions": ("opinion",),
    "shadow_reports": ("shadow_report",),
    "shadow_opinions": ("shadow_opinion",),
}
TIER_KEYS = list(ROLE_TYPES)


def roles(entries: list[dict]) -> dict:
    """Kolik textů poslanec dostal na starost podle role (bez ohledu na výsledek hlasování) a kolik návrhů
    usnesení (vlastních i společných) podepsal. Jen počty z dat, žádné váhy ani body."""
    out = {k: sum(1 for e in entries if e["type"] in types) for k, types in ROLE_TYPES.items()}
    out["motions_signed"] = sum(1 for e in entries if e["type"] in ("motion", "joint_motion"))
    return out


def tier(value: int, values: list[int]) -> str | None:
    """Třetina v delegaci: podíl poslanců s menší hodnotou. 0 = bez třetiny (None), shodná hodnota = shodná třetina.
    top ≥ 2/3, mid ≥ 1/3, jinak low."""
    if not value or not values:
        return None
    below = sum(1 for v in values if v < value) / len(values)
    return "top" if below >= 2 / 3 else "mid" if below >= 1 / 3 else "low"


MIN_COVERAGE = 0.75  # pod tímto podílem období se třetina neurčuje (kratší mandát se nesrovnává)


def coverage(start: str | None, first_start: str | None, until: str | None) -> float | None:
    """Jaký podíl období (od nejdřívějšího začátku mandátu v delegaci do `until`) poslanec v mandátu byl."""
    if not (start and first_start and until):
        return None
    from datetime import date

    d = lambda s: date.fromisoformat(s)
    total = (d(until) - d(first_start)).days
    return min(1.0, (d(until) - d(max(start, first_start))).days / total) if total > 0 else None


def delegation_profile(
    roles_by_mep: dict[str, dict], members: dict[str, str] | None = None, until: str | None = None
) -> dict[str, dict | None]:
    """Profil v české delegaci: u každé kategorie z TIER_KEYS třetina mezi současnými poslanci. Žádné celkové pořadí.

    members = {ID: začátek mandátu} poslanců v mandátu (současná delegace); jen mezi nimi se srovnává.
    Poslanec delegace bez dat má všude 0. Bývalí poslanci profil nedostanou (None), protože srovnávat počty
    za různě dlouhá období nedává smysl. Bez members se srovnává mezi všemi v roles_by_mep.
    Kdo byl v mandátu méně než MIN_COVERAGE období (do dne `until`), třetinu nedostane (tiers_skipped): srovnání
    absolutních počtů s kolegy, kteří mají za sebou celé období, by vyznělo jako verdikt. Čísla zůstávají."""
    if members is None:
        members = {k: None for k in roles_by_mep}
    value = lambda k, key: (roles_by_mep.get(k) or {}).get(key, 0)
    columns = {key: [value(k, key) for k in members] for key in TIER_KEYS}
    first_start = min((v for v in members.values() if v), default=None)
    out: dict[str, dict | None] = {k: None for k in roles_by_mep}
    for k, start in members.items():
        cov = coverage(start, first_start, until)
        skipped = cov is not None and cov < MIN_COVERAGE
        out[k] = {
            "tiers": {key: None if skipped else tier(value(k, key), columns[key]) for key in TIER_KEYS},
            "of": len(members),
            "tiers_skipped": skipped,
            "mandate_from": start if start and first_start and start > first_start else None,
        }
    return out
