import json
from pathlib import Path

from utils.rotation_replay import build_rotation_replay

ROOT = Path(__file__).resolve().parents[1]


def _replay():
    report = json.loads((ROOT / "data" / "benchmark_dagger.json").read_text(encoding="utf-8"))
    overrides = json.loads((ROOT / "data" / "skills" / "thief_skill_overrides.json").read_text(encoding="utf-8"))
    return build_rotation_replay(report, overrides)


def test_replay_matches_uploaded_benchmark_totals():
    replay = _replay()
    summary = replay["summary"]
    assert summary["observed_damage"] == 3952297
    assert summary["observed_dps"] == 42040
    assert summary["observed_casts"] > 0


def test_alacrity_holo_and_repeat_ransacker_close_cooldown_conflicts():
    replay = _replay()
    assert replay["summary"]["cooldown_violations"] == 0
    assert replay["cooldown_adjustments"]
    assert any(row["kind"] == "Repeat Ransacker" for row in replay["cooldown_adjustments"])


def test_verified_artifact_initiative_closes_aggregate_deficit():
    replay = _replay()
    assert replay["summary"]["initiative_spent"] == 156.0
    assert replay["summary"]["confirmed_artifact_initiative_gain"] > 0
    assert replay["summary"]["unmodeled_initiative_income_required"] == 0.0


def test_holo_dancer_reduces_the_next_utility_recharge():
    replay = _replay()
    assert replay["summary"]["holo_utility_consumptions"] == 2
    assert all(row["effective_recharge_s"] <= row["base_recharge_s"] for row in replay["holo_utility_consumptions"])


def test_conditions_are_not_falsely_attributed_to_casts():
    replay = _replay()
    poison = next(row for row in replay["damage_comparison"] if row["skill_id"] == 723)
    assert poison["model_status"] == "aggregate_condition_unattributed"
