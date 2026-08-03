from __future__ import annotations

from typing import Any

from .modifiers import DamageModifiers


def calculate_strike_damage(
    *,
    power: float,
    weapon_strength: float,
    coefficient: float,
    enemy_armor: float,
    critical_chance: float,
    critical_damage: float,
    vulnerability_stacks: int = 0,
    modifiers: DamageModifiers | None = None,
) -> dict[str, Any]:
    """Calculate deterministic and expected strike damage for one hit."""
    modifiers = modifiers or DamageModifiers()
    armor = max(1.0, float(enemy_armor))
    crit_chance = min(1.0, max(0.0, float(critical_chance)))
    crit_multiplier = max(1.0, float(critical_damage))
    vulnerability_factor = 1.0 + min(25, max(0, int(vulnerability_stacks))) * 0.01

    raw = max(0.0, float(weapon_strength)) * max(0.0, float(power)) * max(0.0, float(coefficient)) / armor
    additive_factor = modifiers.additive_strike_factor
    multiplicative_factor = modifiers.multiplicative_strike_factor
    normal = raw * additive_factor * multiplicative_factor * vulnerability_factor
    critical = normal * crit_multiplier
    expected = normal * (1.0 - crit_chance) + critical * crit_chance
    effective_power = max(0.0, float(power)) * (1.0 + crit_chance * (crit_multiplier - 1.0))

    return {
        "raw_damage": raw,
        "normal_hit": normal,
        "critical_hit": critical,
        "expected_hit": expected,
        "effective_power": effective_power,
        "additive_factor": additive_factor,
        "multiplicative_factor": multiplicative_factor,
        "vulnerability_factor": vulnerability_factor,
        "total_factor": additive_factor * multiplicative_factor * vulnerability_factor,
    }
