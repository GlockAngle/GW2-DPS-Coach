import json
from pathlib import Path
from utils.full_benchmark_prediction import build_full_benchmark_prediction, build_saved_benchmark_profile

ROOT = Path(__file__).resolve().parents[1]

def test_saved_profile_has_real_stats_and_duration_bonuses():
    profile = build_saved_benchmark_profile()
    assert profile["snapshot"].power > 1000
    assert profile["snapshot"].condition_damage > 1000
    assert 0.9 < profile["condition_duration_bonus"]["Bleeding"] <= 1.0
    assert 0.9 < profile["condition_duration_bonus"]["Poison"] <= 1.0


def test_prediction_uses_formulas_but_does_not_claim_full_readiness():
    report = json.loads((ROOT / "data/reference/benchmark_dagger.json").read_text())
    overrides = json.loads((ROOT / "data/skills/thief_skill_overrides.json").read_text())
    result = build_full_benchmark_prediction(report, overrides)
    assert result["summary"]["predicted_supported_damage"] > 0
    assert result["summary"]["predicted_supported_dps"] > 0
    assert result["summary"]["full_prediction_ready"] is False
    assert "not observed damage" in result["summary"]["label"].lower()


def test_venomous_volley_does_not_merge_recall():
    report = json.loads((ROOT / "data/reference/benchmark_dagger.json").read_text())
    overrides = json.loads((ROOT / "data/skills/thief_skill_overrides.json").read_text())
    result = build_full_benchmark_prediction(report, overrides)
    volley = next((row for row in result["sources"] if row["skill_id"] == 71852), None)
    # This dagger-only log should not invent axe casts or recall payloads.
    assert volley is None
