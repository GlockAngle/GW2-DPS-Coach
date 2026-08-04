from utils.condition_utils import condition_family, resolve_condition_duration_bonus


def test_all_specific_condition_duration_keys_are_resolved():
    generic = 0.40
    specific = {
        "Bleeding Duration": 0.55,
        "Burning Duration": 0.60,
        "Confusion Duration": 0.65,
        "Poison Duration": 0.73,
        "Torment Duration": 0.80,
    }
    assert resolve_condition_duration_bonus("Bleeding", generic, specific) == 0.55
    assert resolve_condition_duration_bonus("Burning", generic, specific) == 0.60
    assert resolve_condition_duration_bonus("Confusion", generic, specific) == 0.65
    assert resolve_condition_duration_bonus("Poison", generic, specific) == 0.73
    assert resolve_condition_duration_bonus("Torment", generic, specific) == 0.80


def test_condition_duration_aliases_and_legacy_keys_work():
    assert condition_family("Poisoned") == "poison"
    assert condition_family("Bleed") == "bleeding"
    assert resolve_condition_duration_bonus("Poisoned", 0.20, {"Poison": 0.50}) == 0.50
    assert resolve_condition_duration_bonus("Bleed", 0.20, {"bleeding": 0.45}) == 0.45


def test_specific_duration_never_drops_below_generic_and_is_capped():
    assert resolve_condition_duration_bonus("Poison", 0.67, {"Poison Duration": 0.50}) == 0.67
    assert resolve_condition_duration_bonus("Poison", 0.67, {"Poison Duration": 1.20}) == 1.0


def test_potent_poison_example_reaches_duration_cap():
    # 67.2% generic duration + Potent Poison is already combined by Gear Simulator
    # into the Poison Duration total and capped at 100%.
    bonus = resolve_condition_duration_bonus(
        "Poison",
        0.672,
        {"Poison Duration": 1.0},
    )
    assert bonus == 1.0
    assert 2.0 * (1.0 + bonus) == 4.0
    assert 4.0 * (1.0 + bonus) == 8.0


def test_runtime_trait_bonus_fills_stale_metrics_without_double_counting():
    # Empty/stale page metrics: generic 0 plus Potent Poison 33%.
    assert resolve_condition_duration_bonus(
        "Poison", 0.0, {}, additional_specific_bonus=0.33
    ) == 0.33

    # A complete Gear Simulator total already includes the trait. Do not add it twice.
    assert resolve_condition_duration_bonus(
        "Poison", 0.67, {"Poison Duration": 1.0}, additional_specific_bonus=0.33
    ) == 1.0

    # A stale specific value is repaired from generic + active trait.
    assert resolve_condition_duration_bonus(
        "Poison", 0.67, {"Poison Duration": 0.67}, additional_specific_bonus=0.33
    ) == 1.0
