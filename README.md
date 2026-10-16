# EP Watch CZ – výpočty

Otevřené skripty a testy projektu **[EP Watch CZ](https://epwatch.cz)**: web o práci 21 českých europoslanců
v 10. volebním období (od 16. 7. 2024). Všechna čísla na webu počítá kód z tohoto repozitáře, ne AI, a dá se ověřit.

## Co tu je

| Složka | Obsah |
|---|---|
| `scripts/` | stahování dat (HowTheyVote export, EP Open Data API, Wikidata), statistiky (`compute_stats.py`, `benchmarks.py`, `own_work.py`, `group_stats.py` …), skládání dat pro web (`build_web.py`) |
| `tests/` | testy výpočtů (pytest), testovací data mají prefix `MOCK_` nebo leží v `tests/fixtures/` |
| `data/manual/` | ruční doplňky (český překlad témat OEIL, opravy jmen, barvy) |

Web samotný (vzhled, stránky) tady není, zdrojový kód webu je soukromý. **Data**, která web zobrazuje, jsou veřejná na webu
(`/data/*.json`) a řídí se `DATA_LICENSE.md` (HowTheyVote ODbL, EP Open Data CC BY 4.0).

## Spuštění testů

```
pip install -r requirements.txt
python -m pytest -q
```

## Pravidla projektu

- Žádný scraping HTML: jen oficiální API a exporty.
- Žádná vymyšlená data: co zdroj nemá, je `null`.
- Čísla počítá kód (čisté funkce s testy), strana a frakce se berou k datu hlasování.

## Chyba nebo nápad?

Založte **issue** v tomto repozitáři (u čísla uveďte stránku a očekávanou hodnotu) nebo napište přes formulář na webu.

## Licence

Kód: [GNU AGPL-3.0](LICENSE). Kdo kód upraví a nabízí jako službu přes síť, musí zveřejnit i svůj zdrojový kód.
Data: viz [DATA_LICENSE.md](DATA_LICENSE.md).

Tento repozitář se synchronizuje automaticky ze soukromého hlavního repozitáře; změny přímo sem (pull requesty) proto
nepřijímáme, napište issue.
