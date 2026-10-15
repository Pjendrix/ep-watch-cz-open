import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from compute_stats import FormatError  # noqa: E402
from overrides import apply_name_overrides  # noqa: E402

FIX = {"names": {"1": {"given_name": "Klára", "family_name": "Dostálová", "note": "MOCK pozn.", "source": "MOCK_URL"}}}


def write(tmp_path, doc):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_adds_diacritics_with_note(tmp_path):
    meps = [{"id": 1, "name": "Klara DOSTALOVA", "given_name": "Klara", "family_name": "Dostalova"}, {"id": 2, "name": "X"}]
    assert apply_name_overrides(meps, write(tmp_path, FIX)) == 1
    assert (meps[0]["given_name"], meps[0]["family_name"], meps[0]["name"]) == ("Klára", "Dostálová", "Klára DOSTÁLOVÁ")
    assert "MOCK_URL" in meps[0]["name_note"] and "name_note" not in meps[1]


def test_mismatch_raises(tmp_path):
    meps = [{"id": 1, "name": "Jana NOVAKOVA", "given_name": "Jana", "family_name": "Novakova"}]
    with pytest.raises(FormatError, match="nesedí"):
        apply_name_overrides(meps, write(tmp_path, FIX))


def test_missing_source_raises(tmp_path):
    doc = {"names": {"1": {"given_name": "A", "family_name": "B", "note": "x"}}}
    with pytest.raises(FormatError):
        apply_name_overrides([{"id": 1, "given_name": "A", "family_name": "B"}], write(tmp_path, doc))


def test_no_file(tmp_path):
    assert apply_name_overrides([], tmp_path / "chybi.json") == 0


def test_real_overrides_match_current_meps():
    root = Path(__file__).resolve().parent.parent
    if not (root / "data" / "meps.json").exists():  # ve veřejném repozitáři výpočtů nejsou stažená data
        import pytest
        pytest.skip("data/meps.json není k dispozici")
    meps = json.loads((root / "data" / "meps.json").read_text(encoding="utf-8"))["meps"]
    assert apply_name_overrides(meps, root / "data" / "manual" / "overrides.json") >= 1
