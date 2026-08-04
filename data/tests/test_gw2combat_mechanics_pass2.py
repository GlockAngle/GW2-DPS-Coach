from utils.gw2combat_antiquary import build_antiquary_benchmark_package


def _effect_map(package):
    build = package.files['generated/antiquary-build.json']
    return {row['unique_effect_key']: row for row in build['permanent_unique_effects']}


def test_pass2_condition_packet_constants():
    effects = _effect_map(build_antiquary_benchmark_package())
    deadly = effects['Deadly Ambush']['attribute_modifiers'][0]
    assert deadly['attribute'] == 'bleeding_damage_multiplier'
    assert deadly['multiplier'] == 1.3907

    potent = effects['Potent Poison']['attribute_modifiers']
    poison_damage = next(row for row in potent if row['attribute'] == 'poison_damage_multiplier')
    assert poison_damage['addend'] == 0.0248

    corrections = effects['Antiquary condition packet corrections']['attribute_modifiers']
    by_name = {row['attribute']: row['multiplier'] for row in corrections}
    assert by_name['burning_damage_multiplier'] == 1.5030
    assert by_name['torment_damage_multiplier'] == 1.2357


def test_pass2_strike_packet_constant():
    effects = _effect_map(build_antiquary_benchmark_package())
    row = effects['Antiquary strike packet correction']['attribute_modifiers'][0]
    assert row == {'attribute': 'outgoing_strike_damage_multiplier', 'multiplier': 1.0926}
