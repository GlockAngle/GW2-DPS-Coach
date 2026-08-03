import json
from pathlib import Path


def _data():
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "data" / "skills" / "thief_skill_overrides.json").read_text(encoding="utf-8"))


def test_venomous_volley_contains_only_its_own_three_poison_applications():
    skill = _data()["71852"]
    assert skill["conditions"] == [{"condition": "Poison", "stacks": 3, "duration": 2.0}]
    events = skill["condition_events"]
    assert len(events) == 1
    assert events[0]["phase"] == "cast_projectiles"
    assert events[0]["hits"] == 3
    assert events[0]["applications_per_hit"] == 1
    assert events[0]["base_duration"] == 2.0
    assert "recall" not in events[0]["phase"]


def test_recall_axes_is_a_separate_state_dependent_skill():
    skill = _data()["71895"]
    recall = skill["dynamic_recall"]
    assert recall["max_axes_recalled"] == 5
    venomous = next(p for p in recall["source_payloads"] if p["source_skill_id"] == 71852)
    assert venomous["max_axes_from_source"] == 3
    assert venomous["condition_events_per_recalled_axe"] == [
        {"condition": "Poison", "stacks": 1, "base_duration": 2.0}
    ]
    assert all(c["condition"] != "Poison" for c in skill.get("conditions", []))


def test_condition_audit_never_leaves_ambiguous_records_wiki_verified():
    for skill in _data().values():
        flags = [str(x) for x in skill.get("review_flags", [])]
        if any(x.startswith("condition audit:") for x in flags):
            assert skill.get("data_status") != "Wiki verified"
