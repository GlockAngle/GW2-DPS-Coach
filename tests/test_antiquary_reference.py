from pathlib import Path

from utils.antiquary_reference import (
    compare_reference_to_engine,
    load_elite_insights_reference,
)


def test_reference_loads_full_fight_totals():
    root = Path(__file__).resolve().parents[1]
    reference = load_elite_insights_reference(root / "data" / "benchmark_dagger.json")
    assert reference["dps"] == 42040
    assert reference["total_damage"] == 3952297
    assert reference["duration_ms"] == 94013


def test_comparison_does_not_calibrate():
    reference = {
        "dps": 100.0,
        "total_damage": 1000.0,
        "by_skill": [
            {
                "Skill": "Test",
                "Damage type": "strike",
                "Comparison level": "skill + damage type",
                "Reference damage": 1000.0,
                "Reference hits / ticks": 1,
            }
        ],
        "by_damage_type": [
            {
                "Damage type": "strike",
                "Reference damage": 1000.0,
                "Reference hits / ticks": 1,
            }
        ],
    }
    analysis = {
        "dps": 50.0,
        "by_skill": [
            {
                "Skill": "Test",
                "Damage type": "strike",
                "Damage": 500.0,
                "Hits / ticks": 1,
            }
        ],
        "by_damage_type": [
            {"Damage type": "strike", "Damage": 500.0, "Hits / ticks": 1}
        ],
    }
    result = compare_reference_to_engine(reference, analysis)
    assert analysis["dps"] == 50.0
    assert result["dps_difference"] == -50.0
    assert result["skill_comparison"][0]["Engine damage"] == 500.0


def test_condition_reference_is_compared_as_type_aggregate_not_fake_skill():
    reference = {
        "dps": 100.0,
        "total_damage": 1000.0,
        "by_skill": [
            {
                "Skill": "Bleeding",
                "Damage type": "bleeding",
                "Comparison level": "damage-type aggregate",
                "Reference damage": 1000.0,
                "Reference hits / ticks": 10,
            }
        ],
        "by_damage_type": [
            {
                "Damage type": "bleeding",
                "Reference damage": 1000.0,
                "Reference hits / ticks": 10,
            }
        ],
    }
    analysis = {
        "dps": 90.0,
        "by_skill": [
            {
                "Skill": "Death Blossom",
                "Damage type": "bleeding",
                "Damage": 600.0,
                "Hits / ticks": 6,
            },
            {
                "Skill": "Caltrops",
                "Damage type": "bleeding",
                "Damage": 300.0,
                "Hits / ticks": 4,
            },
        ],
        "by_damage_type": [
            {"Damage type": "bleeding", "Damage": 900.0, "Hits / ticks": 10}
        ],
    }
    result = compare_reference_to_engine(reference, analysis)
    rows = result["skill_comparison"]
    assert len(rows) == 1
    assert rows[0]["Skill"] == "All Bleeding"
    assert rows[0]["Engine damage"] == 900.0
    assert rows[0]["Status"] == "damage-type aggregate"


def test_direct_skill_matching_uses_skill_and_damage_type():
    reference = {
        "dps": 100.0,
        "total_damage": 1000.0,
        "by_skill": [
            {
                "Skill": "Death Blossom",
                "Damage type": "strike",
                "Comparison level": "skill + damage type",
                "Reference damage": 100.0,
                "Reference hits / ticks": 3,
            }
        ],
        "by_damage_type": [],
    }
    analysis = {
        "dps": 100.0,
        "by_skill": [
            {
                "Skill": "Death Blossom",
                "Damage type": "strike",
                "Damage": 95.0,
                "Hits / ticks": 3,
            },
            {
                "Skill": "Death Blossom",
                "Damage type": "bleeding",
                "Damage": 900.0,
                "Hits / ticks": 100,
            },
        ],
        "by_damage_type": [],
    }
    result = compare_reference_to_engine(reference, analysis)
    assert result["skill_comparison"][0]["Engine damage"] == 95.0
    assert result["skill_comparison"][0]["Engine hits / ticks"] == 3
