from utils.gw2combat_adapter import analyze_audit
from utils.gw2combat_antiquary import (
    DIRECT_STRIKE_COEFFICIENT_SCALE,
    FORGED_SURFER_ADDITIONAL_BOMB_SCALE,
    _skill_from_override,
)


def test_chak_shield_child_packet_is_generated_and_split():
    skill = _skill_from_override(
        "Zephyrite Sun Crystal",
        {"power_coefficient": 1.0, "hits": 1, "classification": {"weapon": "Artifact"}},
        1000,
    )
    strikes = [row for row in skill["skill_ticks"] if row.get("strike")]
    assert len(strikes) == 4
    audit = {
        "afk_ticks_by_actor": {"player": 2000},
        "tick_events": [
            {"time_ms": 1000, "actor": "golem", "event": {"event_type": "damage_event", "source_actor": "player", "source_skill": "Zephyrite Sun Crystal", "damage_type": "strike", "damage": 4500}},
            {"time_ms": 1150, "actor": "golem", "event": {"event_type": "damage_event", "source_actor": "player", "source_skill": "Zephyrite Sun Crystal", "damage_type": "strike", "damage": 1400}},
        ],
    }
    result = analyze_audit(audit)
    names = {(row["Skill"], row["Damage type"]) for row in result["by_skill"]}
    assert ("Chak Shield", "strike") in names
    assert ("Zephyrite Sun Crystal", "strike") in names


def test_full_audit_span_is_used_for_combat_time():
    audit = {
        "afk_ticks_by_actor": {"player": 94013},
        "tick_events": [
            {"time_ms": 1000, "actor": "golem", "event": {"event_type": "damage_event", "source_actor": "player", "source_skill": "Test", "damage_type": "strike", "damage": 100}},
            {"time_ms": 93000, "actor": "golem", "event": {"event_type": "damage_event", "source_actor": "player", "source_skill": "Test", "damage_type": "strike", "damage": 100}},
        ],
    }
    result = analyze_audit(audit)
    assert result["combat_time_ms"] == 94013


def test_final_scales_are_source_specific():
    assert DIRECT_STRIKE_COEFFICIENT_SCALE["Backstab"] < 1.0
    assert DIRECT_STRIKE_COEFFICIENT_SCALE["Metal Legion Guitar (Rockout)"] > 2.0
    assert FORGED_SURFER_ADDITIONAL_BOMB_SCALE > 1.45
