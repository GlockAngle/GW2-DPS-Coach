import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _specializations():
    tree = ast.parse((ROOT / 'utils' / 'thief_traits.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, 'id', None) == 'THIEF_SPECIALIZATIONS':
            return ast.literal_eval(node.value)
    raise AssertionError('THIEF_SPECIALIZATIONS not found')


def test_every_thief_trait_has_a_mapping():
    specs = _specializations()
    ids = {str(tid) for spec in specs.values() for tid in spec['minor'] + spec['major']}
    overrides = json.loads((ROOT / 'data' / 'traits' / 'thief_effect_overrides.json').read_text(encoding='utf-8'))
    mapped = {key for key in overrides if not key.startswith('_')}
    assert ids == mapped


def test_no_trait_is_left_data_only():
    overrides = json.loads((ROOT / 'data' / 'traits' / 'thief_effect_overrides.json').read_text(encoding='utf-8'))
    statuses = {record.get('status') for key, record in overrides.items() if not key.startswith('_')}
    assert 'data_only' not in statuses
    assert statuses <= {'implemented', 'assumption', 'event_ready'}


def test_event_ready_traits_have_packets():
    overrides = json.loads((ROOT / 'data' / 'traits' / 'thief_effect_overrides.json').read_text(encoding='utf-8'))
    for key, record in overrides.items():
        if key.startswith('_') or record.get('status') != 'event_ready':
            continue
        assert record.get('event_trigger')
        assert isinstance(record.get('event_packet'), list)
