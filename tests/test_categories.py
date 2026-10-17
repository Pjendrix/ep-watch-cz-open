import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import categories as c  # noqa: E402


def v(*codes):
    return {"topics": {"oeil": [{"code": x, "label": "MOCK"} for x in codes]}}


def test_primary_follows_priority_not_order():
    # AGILE: obrana má přednost před průmyslem a vědou
    assert (
        c.categories_for(v("3.45.02", "3.50.04", "6.10.02")) == ["def", "dig", "eco"]
        or c.categories_for(v("3.45.02", "3.50.04", "6.10.02"))[0] == "def"
    )
    # nákladní auta: klima před dopravou před průmyslem
    assert c.categories_for(v("2.10.03", "3.20.05", "3.40.03", "3.70.02")) == ["env", "tra", "eco"]


def test_specific_codes_win_over_prefix():
    assert c.category_of_code("3.40.09") == "def" and c.category_of_code("3.40.03") == "eco"
    assert c.category_of_code("4.60.04.04") == "agr" and c.category_of_code("4.60.02") == "soc"
    assert c.category_of_code("1.20.09") == "dig" and c.category_of_code("1.20.20") == "civ"
    assert c.category_of_code("2.70.02") == "fin" and c.category_of_code("8.70") == "fin"


def test_no_topics_no_category():
    assert c.categories_for({}) == [] and c.categories_for(v()) == []
    assert c.categories_for(v("9.10")) == []


def test_every_category_has_label_and_icon():
    assert set(c.ORDER) == set(c.LABEL) == set(c.ICON) and len(c.ORDER) == 12
