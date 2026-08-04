from utils.gw2combat_adapter import analyze_audit


def test_forged_surfer_child_bombs_are_attributed_separately():
    audit = {"tick_events": [
        {"time_ms": 100, "actor": "golem", "event": {"event_type": "damage_event", "source_actor": "player", "source_skill": "Forged Surfer Dash", "damage_type": "strike", "damage": 6000}},
        {"time_ms": 200, "actor": "golem", "event": {"event_type": "damage_event", "source_actor": "player", "source_skill": "Forged Surfer Dash", "damage_type": "strike", "damage": 3000}},
    ]}
    rows = analyze_audit(audit)["by_skill"]
    keyed = {(r["Skill"], r["Damage type"]): r for r in rows}
    assert keyed[("Forged Surfer Dash", "strike")]["Damage"] == 6000
    assert keyed[("Forged Surfer Dash (Additional Bombs)", "strike")]["Damage"] == 3000
