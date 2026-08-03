from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WeaponStrengthRange:
    minimum: float
    midpoint: float
    maximum: float


# Level-80 exotic/ascended weapon-strength ranges used by the calculator.
# Midpoint is the expected average of the minimum and maximum roll.
WEAPON_STRENGTHS: dict[str, WeaponStrengthRange] = {
    "Axe": WeaponStrengthRange(900.0, 1000.0, 1100.0),
    "Dagger": WeaponStrengthRange(970.0, 1000.0, 1030.0),
    "Focus": WeaponStrengthRange(873.0, 900.0, 927.0),
    "Greatsword": WeaponStrengthRange(1045.0, 1100.0, 1155.0),
    "Pistol": WeaponStrengthRange(920.0, 1000.0, 1080.0),
    "Rifle": WeaponStrengthRange(1035.0, 1150.0, 1265.0),
    "Scepter": WeaponStrengthRange(940.0, 1000.0, 1060.0),
    "Shield": WeaponStrengthRange(846.0, 900.0, 954.0),
    "Short Bow": WeaponStrengthRange(905.0, 1000.0, 1095.0),
    "Spear": WeaponStrengthRange(950.0, 1000.0, 1050.0),
    "Staff": WeaponStrengthRange(1034.0, 1100.0, 1166.0),
    "Sword": WeaponStrengthRange(950.0, 1000.0, 1050.0),
    "Torch": WeaponStrengthRange(828.0, 900.0, 972.0),
    "Trident": WeaponStrengthRange(950.0, 1000.0, 1050.0),
    "Unarmed": WeaponStrengthRange(656.0, 691.0, 725.0),
}


def get_weapon_strength(weapon: str, mode: str = "Midpoint") -> float:
    profile = WEAPON_STRENGTHS.get(weapon)
    if profile is None:
        raise ValueError(f"Unknown weapon type: {weapon}")
    values = {
        "Minimum": profile.minimum,
        "Midpoint": profile.midpoint,
        "Maximum": profile.maximum,
    }
    if mode not in values:
        raise ValueError(f"Unknown weapon-strength mode: {mode}")
    return values[mode]
