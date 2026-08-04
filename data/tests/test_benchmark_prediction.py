import json
from pathlib import Path
from utils.benchmark_prediction import build_condition_attribution

ROOT = Path(__file__).resolve().parents[1]


def _result():
    report = json.loads((ROOT / "data" / "benchmark_dagger.json").read_text(encoding="utf-8"))
    overrides = json.loads((ROOT / "data" / "skills" / "thief_skill_overrides.json").read_text(encoding="utf-8"))
    return build_condition_attribution(report, overrides)


def test_attribution_never_claims_independent_prediction():
    result = _result()
    assert result["summary"]["independent_prediction_ready"] is False
    assert "not independently simulated" in result["summary"]["label"]


def test_explicit_packets_attribute_poison_and_bleeding():
    result = _result()
    names = {row["condition"] for row in result["sources"]}
    assert "Poison" in names
    assert "Bleeding" in names


def test_attribution_preserves_each_mapped_condition_total():
    result = _result()
    for condition in result["conditions"]:
        if condition["source_coverage"] != "unmapped":
            assert condition["attributed_damage"] == condition["observed_damage"]


def test_all_observed_condition_types_have_explicit_packets():
    result = _result()
    assert {row["condition"] for row in result["conditions"]} == {"Bleeding", "Poison", "Burning", "Torment", "Confusion"}
    assert all(row["source_coverage"] != "unmapped" for row in result["conditions"])
