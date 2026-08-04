from utils.gw2combat_antiquary import build_antiquary_benchmark_package


def _skill(build, name):
    return next(row for row in build["skills"] if row["skill_key"] == name)


def test_mistburn_uses_benchmark_verified_per_pulse_coefficient():
    package = build_antiquary_benchmark_package()
    build = package.files["generated/antiquary-build.json"]
    skill = _skill(build, "Mistburn Mortar")
    strikes = [row for row in skill["skill_ticks"] if row.get("strike")]
    assert len(strikes) == 5
    assert all(abs(row["damage_coefficient"] - 0.76435) < 1e-9 for row in strikes)


def test_forged_surfer_has_separate_scaled_child_bomb_packets():
    package = build_antiquary_benchmark_package()
    build = package.files["generated/antiquary-build.json"]
    skill = _skill(build, "Forged Surfer Dash")
    strikes = [row for row in skill["skill_ticks"] if row.get("strike")]
    assert [round(row["damage_coefficient"], 3) for row in strikes] == [3.864, 1.805, 1.805, 1.805, 1.805]


def test_skritt_scuffle_no_longer_creates_engine_only_strike_damage():
    package = build_antiquary_benchmark_package()
    build = package.files["generated/antiquary-build.json"]
    skill = _skill(build, "Skritt Scuffle")
    assert not any(row.get("strike") for row in skill.get("skill_ticks", []))
