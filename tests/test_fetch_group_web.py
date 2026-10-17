import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_group_web as f  # noqa: E402

TITLES = {"AAA": "MOCK Skupina A", "BBB": "MOCK Skupina B"}


def entity(title, urls, rank="normal"):
    return {
        "sitelinks": {"cswiki": {"title": title}},
        "claims": {"P856": [{"rank": rank, "mainsnak": {"datavalue": {"value": u}}} for u in urls]},
    }


def test_parse_websites_picks_preferred_https():
    payload = {
        "entities": {
            "Q1": entity("MOCK Skupina A", ["http://old.example", "https://a.example"]),
            "Q2": {
                **entity("MOCK Skupina B", ["https://b.example"]),
                "claims": {
                    "P856": [
                        {"rank": "normal", "mainsnak": {"datavalue": {"value": "https://x.example"}}},
                        {"rank": "preferred", "mainsnak": {"datavalue": {"value": "https://b.example"}}},
                    ]
                },
            },
        }
    }
    out = f.parse_websites(payload, TITLES)
    assert out["AAA"] == {"web": "https://a.example", "wikidata": "https://www.wikidata.org/wiki/Q1"}
    assert out["BBB"]["web"] == "https://b.example"


def test_missing_item_or_website_is_format_error():
    with pytest.raises(f.FormatError):
        f.parse_websites({"entities": {"-1": {"missing": ""}}}, TITLES)
    with pytest.raises(f.FormatError):
        f.parse_websites({"entities": {"Q1": entity("MOCK Skupina A", []), "Q2": entity("MOCK Skupina B", ["https://b.example"])}}, TITLES)
    with pytest.raises(f.FormatError):
        f.parse_websites({}, TITLES)
