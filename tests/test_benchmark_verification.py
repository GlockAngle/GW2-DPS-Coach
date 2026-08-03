import json
from pathlib import Path
from utils.benchmark_verification import build_verification_report
ROOT = Path(__file__).resolve().parents[1]

def _load(name):
    return json.loads((ROOT / 'data' / name).read_text(encoding='utf-8'))

def test_gate_does_not_call_observed_dps_a_prediction():
    result = build_verification_report(
        _load('benchmark_rotation_replay.json'),
        _load('benchmark_dagger_readiness.json'),
        _load('benchmark_condition_attribution.json'),
        _load('benchmark_antiquary_artifacts.json'),
    )
    assert result['summary']['observed_dps_is_prediction'] is False
    assert result['summary']['simulation_ready'] is False

def test_gate_closes_condition_and_cooldown_blockers():
    result = _load('benchmark_verification_report.json')
    statuses = {r['category']: r for r in result['categories']}
    assert statuses['Condition source mapping']['status'] == 'VERIFIED'
    assert statuses['Cooldown/state legality']['status'] == 'VERIFIED'
    assert statuses['Core dagger skills']['status'] == 'VERIFIED'
    assert statuses['Independent damage formulas']['status'] == 'BLOCKED'
