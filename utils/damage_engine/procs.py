from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProcEffect:
    """Data contract for future sigil, relic and trait proc simulation."""

    name: str
    trigger: str
    internal_cooldown: float = 0.0
    chance: float = 1.0
    strike_coefficient: float = 0.0
    conditions: tuple[dict[str, float], ...] = field(default_factory=tuple)
    stacks: int = 1
    duration: float = 0.0
    implemented: bool = False

    @property
    def supported_trigger(self) -> bool:
        return self.trigger in {
            "on_hit",
            "on_critical_hit",
            "on_weapon_swap",
            "on_interrupt",
            "on_heal",
        }
