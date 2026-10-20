"""Jména a názvy stran a frakcí jsou na webu i kartách stejné (zadání karty hlasování 20. 10. 2026, K0)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import overrides as ov  # noqa: E402

DATA = ROOT / "data"


@pytest.mark.skipif(not (DATA / "meps.json").exists(), reason="data nejsou (veřejný export)")
def test_names_in_meps_json_match_profiles():
    meps = json.loads((DATA / "meps.json").read_text(encoding="utf-8"))["meps"]
    for m in meps:
        prof_path = DATA / "meps" / f"{m['id']}.json"
        if not prof_path.exists():
            continue
        prof = json.loads(prof_path.read_text(encoding="utf-8"))["mep"]
        assert (m["given_name"], m["family_name"]) == (prof["given_name"], prof["family_name"])


def test_party_and_group_labels_applied(tmp_path):
    (tmp_path / "party_labels.json").write_text(json.dumps({"parties": {"1": "MOCK čitelná"}}), encoding="utf-8")
    (tmp_path / "group_labels.json").write_text(json.dumps({"groups": {"PFE": "Patrioti"}}), encoding="utf-8")
    meps = [
        {
            "parties": [{"org_id": "1", "short_label": "MOCK_P"}, {"org_id": "2", "short_label": "Ind."}],
            "groups": [{"code": "PFE", "short_label": "PfE"}],
        }
    ]
    assert ov.apply_party_labels(meps, tmp_path / "party_labels.json") == 2
    assert meps[0]["parties"][0] == {"org_id": "1", "short_label": "MOCK čitelná", "short_label_ep": "MOCK_P"}
    assert meps[0]["parties"][1]["short_label"] == "Ind."  # nezávislí podle rodu, ne z číselníku
    assert meps[0]["groups"][0]["short_label"] == "Patrioti"


@pytest.mark.skipif(not (DATA / "parties.json").exists(), reason="data nejsou (veřejný export)")
def test_no_raw_ep_abbreviations_in_parties_and_groups():
    parties = {p["short_label"] for p in json.loads((DATA / "parties.json").read_text(encoding="utf-8"))}
    groups = {g["short_label"] for g in json.loads((DATA / "groups.json").read_text(encoding="utf-8"))}
    assert not parties & {"TOP09/STAN", "PIR", "AUTO", "PSH", "ANO 2011"}
    assert not groups & {"PfE", "Greens/EFA", "The Left", "Non-attached"}
