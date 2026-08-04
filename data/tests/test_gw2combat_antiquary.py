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


def test_benchmark_replay_skills_do_not_block_or_skip_logged_casts():
    package = build_antiquary_benchmark_package()
    build = package.files['generated/antiquary-build.json']
    benchmark_names = set(package.coverage['expected_cast_counts'])
    generated = {skill['skill_key']: skill for skill in build['skills'] if skill['skill_key'] in benchmark_names}
    assert set(generated) == benchmark_names
    assert package.coverage['replay_mode'] == 'exact_log_timestamps'
    for skill in generated.values():
        assert skill['cast_duration'] == [0, 0]
        assert skill['cooldown'] == [0, 0]
        assert skill['instant_cast_only_when_not_in_animation'] is False


def test_rotation_csv_preserves_full_two_digit_timestamps():
    package = build_antiquary_benchmark_package()
    rotation = package.files['generated/antiquary-rotation.csv']
    lines = rotation.splitlines()
    assert lines[0] == 'rotation'
    assert all(', Time: ' in line for line in lines[1:])
    assert any('Time: 93.800s' in line for line in lines)
    assert not any(',Time: ' in line for line in lines[1:])
