from utils.gw2combat_adapter import (
    VENDOR_ROOT,
    audit_summary,
    engine_status,
    load_bundled_example,
    validate_encounter_references,
)


def test_vendor_source_is_bundled():
    assert (VENDOR_ROOT / "src" / "main.cpp").exists()
    assert (VENDOR_ROOT / "LICENSE.txt").exists()


def test_bundled_example_can_be_resolved():
    encounter, files = load_bundled_example()
    assert encounter.get("actors")
    assert files
    assert validate_encounter_references(encounter, files) == []


def test_missing_references_are_reported():
    encounter = {"actors": [{"build_path": "build.json", "rotation_path": "rotation.csv"}]}
    missing = validate_encounter_references(encounter, {})
    assert "actors[0].build_path: build.json" in missing
    assert "actors[0].rotation_path: rotation.csv" in missing


def test_audit_summary_is_conservative():
    summary = audit_summary([{"type": "DAMAGE", "damage": 123}, {"type": "SKILL_CASTS"}])
    assert summary["damage_events"] == 1
    assert summary["total_damage"] == 123


def test_status_has_message():
    assert engine_status().message


def test_analyze_real_tick_event_schema():
    from utils.gw2combat_adapter import analyze_audit

    audit = {
        "tick_events": [
            {"time_ms": 100, "actor": "player", "event": {"event_type": "skill_cast_begin_event", "skill": "Death Blossom", "cast_duration": 500}},
            {"time_ms": 200, "actor": "golem", "event": {"event_type": "damage_event", "source_actor": "player", "source_skill": "Death Blossom", "damage_type": "strike", "damage": 1000}},
            {"time_ms": 1200, "actor": "golem", "event": {"event_type": "damage_event", "source_actor": "player", "source_skill": "Death Blossom", "damage_type": "poison", "damage": 500}},
            {"time_ms": 1200, "actor": "player", "event": {"event_type": "damage_event", "source_actor": "golem", "source_skill": "Hit", "damage_type": "strike", "damage": 9999}},
        ],
        "afk_ticks_by_actor": {"player": 50},
    }
    result = analyze_audit(audit)
    assert result["damage_events"] == 2
    assert result["total_damage"] == 1500
    assert result["combat_time_ms"] == 1200
    assert result["dps"] == 1250
    assert result["cast_counts"]["Death Blossom"] == 1
    assert result["afk_ms"] == 50
    assert result["by_skill"][0]["Skill"] == "Death Blossom"
