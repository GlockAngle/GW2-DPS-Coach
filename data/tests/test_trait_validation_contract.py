import json
from pathlib import Path


DATA = json.loads(Path('data/traits/thief_effect_overrides.json').read_text(encoding='utf-8'))


def _record(trait_id: int):
    return DATA[str(trait_id)]


def test_deadly_ambition_has_live_stat_and_saved_event_part():
    record = _record(1164)
    effects = record['effects']
    assert any(e.get('type') == 'attribute_bonus' and e.get('attribute') == 'Condition Damage' and e.get('value') == 180 and e.get('state') == 'applied_now' for e in effects)
    assert any(e.get('type') == 'apply_condition' and e.get('condition') == 'Poison' and e.get('state') == 'event_engine' for e in effects)


def test_potent_poison_contract():
    record = _record(1291)
    assert record['modifiers']['poison'] == 0.33
    assert record['modifiers']['Poison Duration'] == 0.33


def test_representative_handlers_remain_mapped():
    expected = {
        1157: 'lead_attacks',
        1269: 'executioner',
        2136: 'one_in_the_chamber',
        2348: 'combat_high',
    }
    for trait_id, handler in expected.items():
        assert _record(trait_id).get('handler') == handler
        assert _record(trait_id).get('effects')
