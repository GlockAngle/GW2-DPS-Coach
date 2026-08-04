from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .modifiers import DamageModifiers


@dataclass(frozen=True)
class ConditionFormula:
    base: float
    coefficient: float


# PvE level-80 damage per stack per second / activation.
CONDITION_FORMULAS: dict[str, ConditionFormula] = {
    "Bleeding": ConditionFormula(22.0, 0.06),
    "Burning": ConditionFormula(131.0, 0.155),
    "Poison": ConditionFormula(33.5, 0.06),
    "Torment (stationary)": ConditionFormula(31.8, 0.09),
    "Torment (moving)": ConditionFormula(22.0, 0.06),
    "Confusion (tick)": ConditionFormula(18.25, 0.05),
    "Confusion (activation)": ConditionFormula(16.24, 0.0325),
}


def calculate_condition_damage(
    *,
    condition_damage: float,
    vulnerability_stacks: int = 0,
    modifiers: DamageModifiers | None = None,
    enemy_movement_uptime: float = 0.0,
    enemy_attack_speed: float = 1.0,
) -> dict[str, dict[str, Any]]:
    """Calculate neutral condition damage values.

    Values are per stack per second except Confusion activation, which is per
    enemy skill activation. The weighted Torment row averages stationary and
    moving target states using the selected movement uptime.
    """
    modifiers = modifiers or DamageModifiers()
    condi = max(0.0, float(condition_damage))
    vuln = 1.0 + min(25, max(0, int(vulnerability_stacks))) * 0.01
    moving = min(1.0, max(0.0, float(enemy_movement_uptime)))
    attack_speed = max(0.0, float(enemy_attack_speed))

    rows: dict[str, dict[str, Any]] = {}
    for name, formula in CONDITION_FORMULAS.items():
        raw = formula.base + formula.coefficient * condi
        condition_name = name.split(" (")[0]
        modifier_factor = modifiers.condition_factor(condition_name)
        final = raw * modifier_factor * vuln
        rows[name] = {
            "base": formula.base,
            "coefficient": formula.coefficient,
            "raw_damage": raw,
            "modifier_factor": modifier_factor,
            "vulnerability_factor": vuln,
            "final_damage": final,
        }

    stationary = rows["Torment (stationary)"]["final_damage"]
    moving_damage = rows["Torment (moving)"]["final_damage"]
    rows["Torment (weighted)"] = {
        "base": None,
        "coefficient": None,
        "raw_damage": (
            rows["Torment (stationary)"]["raw_damage"] * (1.0 - moving)
            + rows["Torment (moving)"]["raw_damage"] * moving
        ),
        "modifier_factor": modifiers.condition_factor("Torment"),
        "vulnerability_factor": vuln,
        "final_damage": stationary * (1.0 - moving) + moving_damage * moving,
    }
    rows["Confusion (activation DPS)"] = {
        **rows["Confusion (activation)"],
        "final_damage": rows["Confusion (activation)"]["final_damage"] * attack_speed,
        "attacks_per_second": attack_speed,
    }
    return rows
