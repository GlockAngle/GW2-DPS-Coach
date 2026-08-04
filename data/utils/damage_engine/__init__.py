"""Class-neutral Guild Wars 2 damage calculation primitives."""

from .weapon_strength import WEAPON_STRENGTHS, get_weapon_strength
from .strike_damage import calculate_strike_damage
from .condition_damage import CONDITION_FORMULAS, calculate_condition_damage
from .modifiers import DamageModifiers, ModifierSource
from .procs import ProcEffect

__all__ = [
    "WEAPON_STRENGTHS",
    "get_weapon_strength",
    "calculate_strike_damage",
    "CONDITION_FORMULAS",
    "calculate_condition_damage",
    "DamageModifiers",
    "ModifierSource",
    "ProcEffect",
]
