import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_benchmark_audit_is_bound_to_uploaded_log_build():
    audit = _load("data/benchmark_dagger_skill_audit.json")
    source = audit["summary"]["source_log"]
    assert source["fight_name"] == "Standard Kitty Golem"
    assert source["game_build"] == 204489
    assert source["elite_insights_version"] == "3.26.0.0"


def test_benchmark_core_cast_counts_match_uploaded_json():
    audit = _load("data/benchmark_dagger_skill_audit.json")
    by_id = {row["id"]: row for row in audit["benchmark_skills"]}
    assert by_id[13006]["cast_count"] == 39  # Death Blossom
    assert by_id[13037]["cast_count"] == 5   # Spider Venom
    assert by_id[56898]["cast_count"] == 4   # Thousand Needles trigger
    assert by_id[77397]["cast_count"] == 5   # Skritt Swipe


def test_conditions_without_events_are_not_rotation_ready():
    audit = _load("data/benchmark_dagger_skill_audit.json")
    for row in audit["benchmark_skills"]:
        if row["library_conditions"] and not row["has_explicit_condition_events"]:
            assert row["status"] == "Needs verification"


def test_venomous_volley_and_recall_remain_separate():
    overrides = _load("data/skills/thief_skill_overrides.json")
    volley = overrides["71852"]
    recall = overrides["71895"]
    assert volley["condition_events"][0]["hits"] == 3
    assert volley["condition_events"][0]["base_duration"] == 2.0
    assert "dynamic_recall" not in volley
    assert recall["dynamic_recall"]["source_payloads"][0]["source_skill_id"] == 71852
