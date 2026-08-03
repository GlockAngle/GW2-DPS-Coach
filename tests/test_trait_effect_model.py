import json
from pathlib import Path


def _payload():
    return json.loads(Path('data/traits/thief_effect_overrides.json').read_text(encoding='utf-8'))


def test_every_trait_has_effect_level_records():
    data = _payload()
    records = [value for key, value in data.items() if not key.startswith('_')]
    assert len(records) == 108
    assert all(record.get('effects') for record in records)


def test_effect_states_are_supported():
    allowed = {'applied_now', 'event_engine', 'needs_implementation'}
    for key, record in _payload().items():
        if key.startswith('_'):
            continue
        assert all(effect.get('state') in allowed for effect in record['effects'])


def test_deadly_ambition_keeps_both_effects():
    record = next(
        value for key, value in _payload().items()
        if not key.startswith('_') and value.get('handler') == 'deadly_ambition'
    )
    states = {(effect.get('type'), effect.get('state')) for effect in record['effects']}
    assert ('attribute_bonus', 'applied_now') in states
    assert ('apply_condition', 'event_engine') in states
