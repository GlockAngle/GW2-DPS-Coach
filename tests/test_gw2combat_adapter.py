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
