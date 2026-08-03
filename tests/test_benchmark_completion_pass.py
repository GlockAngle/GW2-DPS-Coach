import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_pve_mode_facts_are_not_summed():
    data = load_json("data/skills/thief_skill_overrides.json")
    assert data["13004"]["hits"] == 2
    assert data["13004"]["power_coefficient"] == 0.8
    assert data["13005"]["hits"] == 1
    assert data["13005"]["power_coefficient"] == 3.0
    assert data["13087"]["hits"] == 1
    assert data["13087"]["power_coefficient"] == 0.8
    assert data["13108"]["hits"] == 1
    assert data["13108"]["power_coefficient"] == 1.2


def test_condition_packets_are_explicit():
    data = load_json("data/skills/thief_skill_overrides.json")
    blossom = data["13006"]["condition_events"][0]
    assert blossom["hits"] == 3
    assert blossom["stacks_per_application"] == 2
    assert blossom["base_duration"] == 6.0

    caltrops = data["13028"]["condition_events"][0]
    assert caltrops["hits"] == 10
    assert caltrops["interval"] == 1.0

    venom = data["13037"]["condition_events"][0]
    assert venom["charges"] == 6
    assert venom["base_duration"] == 3.0


def test_readiness_keeps_artifacts_blocked():
    readiness = load_json("data/benchmark_dagger_readiness.json")
    assert readiness["summary"]["ready_skill_records"] == 9
    assert "BLOCKED" in readiness["summary"]["rotation_engine_status"]
    statuses = {row["id"]: row["status"] for row in readiness["records"]}
    assert statuses[13006] == "Ready"
    assert statuses[77277].startswith("State-dependent")
