from utils.combat_engine_v1 import CharacterSnapshot, ConditionEvent, StrikeEvent, engine_readiness, simulate_condition_event, simulate_strike_event

def _snapshot():
    return CharacterSnapshot(power=2500, condition_damage=1800)

def test_strike_event_is_independent_formula_output():
    result = simulate_strike_event(_snapshot(), StrikeEvent("Test hit", coefficient=1.0, hits=2))
    assert result["expected_total_damage"] > 0
    assert result["expected_total_damage"] == result["expected_damage_per_hit"] * 2

def test_condition_event_uses_stack_seconds():
    result = simulate_condition_event(_snapshot(), ConditionEvent("Test poison", "Poison", stacks=1, duration_s=2, applications=3))
    assert result["stack_seconds"] == 6
    assert result["expected_total_damage"] > 0

def test_total_prediction_gate_stays_closed_without_timeline_and_modifiers():
    gate = engine_readiness(_snapshot(), timeline_complete=False, modifiers_complete=False)
    assert gate["ready_for_total_prediction"] is False
    assert len(gate["blockers"]) == 2

def test_total_prediction_gate_can_open_with_complete_inputs():
    assert engine_readiness(_snapshot(), timeline_complete=True, modifiers_complete=True)["ready_for_total_prediction"] is True
