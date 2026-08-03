from utils.gw2combat_adapter import validate_encounter_references
from utils.gw2combat_antiquary import build_antiquary_benchmark_package


def test_antiquary_package_has_full_rotation_and_valid_refs():
    package = build_antiquary_benchmark_package()
    assert package.coverage['casts'] > 100
    assert package.coverage['unique_skills'] > 10
    assert validate_encounter_references(package.encounter, package.files) == []


def test_antiquary_package_contains_verified_core_skills():
    package = build_antiquary_benchmark_package()
    supported = set(package.coverage['supported_names'])
    assert 'Death Blossom' in supported
    assert 'Spider Venom' in supported
    assert 'Thousand Needles' in supported


def test_force_is_a_separate_multiplier_in_generated_build():
    package = build_antiquary_benchmark_package()
    build = package.files['generated/antiquary-build.json']
    force = next(x for x in build['permanent_unique_effects'] if x['unique_effect_key'] == 'Superior Sigil of Force')
    modifier = force['attribute_modifiers'][0]
    assert modifier['attribute'] == 'outgoing_strike_damage_multiplier'
    assert modifier['multiplier'] == 1.05
