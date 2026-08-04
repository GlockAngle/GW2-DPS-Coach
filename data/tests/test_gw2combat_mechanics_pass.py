from utils.gw2combat_antiquary import build_antiquary_benchmark_package


def _skill(build, name):
    return next(row for row in build["skills"] if row["skill_key"] == name)


def test_dynamic_trait_state_modifiers_are_present():
    package = build_antiquary_benchmark_package()
    build = package.files["generated/antiquary-build.json"]
    effects = {row["unique_effect_key"]: row for row in build["permanent_unique_effects"]}
    state = effects["Lead Attacks and Combat High (EI state replay)"]["attribute_modifiers"]
    values = {row["attribute"]: row["multiplier"] for row in state}
    assert 1.25 < values["outgoing_condition_damage_multiplier"] < 1.28
    assert 1.31 < values["outgoing_strike_damage_multiplier"] < 1.35
    deadly = effects["Deadly Ambush"]["attribute_modifiers"][0]
    assert deadly == {"attribute": "bleeding_damage_multiplier", "multiplier": 1.3907}


def test_mistburn_uses_per_pulse_coefficient():
    package = build_antiquary_benchmark_package()
    build = package.files["generated/antiquary-build.json"]
    skill = _skill(build, "Mistburn Mortar")
    strikes = [row for row in skill["skill_ticks"] if row.get("strike")]
    assert len(strikes) == 5
    assert all(row["damage_coefficient"] == 0.5 for row in strikes)


def test_forged_surfer_has_child_bomb_strikes():
    package = build_antiquary_benchmark_package()
    build = package.files["generated/antiquary-build.json"]
    skill = _skill(build, "Forged Surfer Dash")
    strikes = [row for row in skill["skill_ticks"] if row.get("strike")]
    assert [row["damage_coefficient"] for row in strikes] == [2.4, 1.2, 1.2, 1.2, 1.2]


def test_skritt_swipe_applies_deadly_ambush_bleeding():
    package = build_antiquary_benchmark_package()
    build = package.files["generated/antiquary-build.json"]
    skill = _skill(build, "Skritt Swipe")
    applications = [
        app
        for tick in skill["skill_ticks"]
        for app in tick.get("on_pulse_effect_applications", [])
    ]
    assert {"effect": "BLEEDING", "base_duration_ms": 10000, "num_stacks": 3, "direction": "OUTGOING"} in applications
