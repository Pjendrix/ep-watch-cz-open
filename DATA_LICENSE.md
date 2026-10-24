# Licence dat

Licence GNU AGPL-3.0 v souboru `LICENSE` platí jen pro **výpočty** (skripty v `scripts/` a testy ve veřejném repozitáři). Zdrojový kód webu samotného je soukromý.
Pro data platí licence jejich zdrojů:

| Co | Zdroj | Licence |
|---|---|---|
| Hlasování a vše z nich spočítané (`data/votes/`, `data/stats.json`, `data/overview.json`, `data/meps/`, `data/parties/`, `data/decisive.json`, `data/splits.json`, `data/session.json`, `data/agreement.json`) | [HowTheyVote.eu](https://howtheyvote.eu), [datový export](https://github.com/HowTheyVote/data) | [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/) – při dalším šíření databáze uveďte zdroj a sdílejte za stejných podmínek |
| Poslanci, mandáty, frakce, strany, výbory, vlastní práce, pozměňovací návrhy (`data/meps.json`, `data/proposals.json`, `data/own_work.json`, `data/amendments.json`, `data/amendments_state.json`) | [EP Open Data](https://data.europarl.europa.eu), u PN ve výborech i DOCX z registru EP | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) – © European Union, Source: EP |
| Portréty (na webu v `assets/photos/`) | Evropský parlament | © European Union – Source: EP |
| Písmo Plus Jakarta Sans (na webu v `assets/fonts/`) | [The Plus Jakarta Sans Project Authors](https://github.com/tokotype/PlusJakartaSans) | SIL Open Font License 1.1 (`assets/fonts/OFL.txt` na webu) |
| Srovnání s celým EP (`data/benchmarks.json`) | spočítáno z HowTheyVote.eu | ODbL 1.0 |
| Ruční doplňky (`data/manual/`) | EP Watch CZ (barvy, český překlad názvů témat OEIL – neoficiální) | jako data, která doplňují (ODbL) |

Každá týdenní aktualizace dat má git tag `data-RRRR-MM-DD`.
