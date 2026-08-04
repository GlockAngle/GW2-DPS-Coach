from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModifierSource:
    name: str
    bonus: float


@dataclass(frozen=True)
class DamageModifiers:
    """Class-neutral damage modifier buckets with auditable sources.

    Bonuses use decimals: 0.05 means +5%. Additive strike bonuses are summed.
    Global and condition-specific condition bonuses are summed within their
    bucket, then multiplied by incoming damage modifiers such as Vulnerability.
    """

    additive_strike_sources: tuple[ModifierSource, ...] = field(default_factory=tuple)
    multiplicative_strike_sources: tuple[tuple[str, float], ...] = field(default_factory=tuple)
    global_condition_sources: tuple[ModifierSource, ...] = field(default_factory=tuple)
    condition_specific_sources: dict[str, tuple[ModifierSource, ...]] = field(default_factory=dict)

    @property
    def additive_strike(self) -> float:
        return sum(float(source.bonus) for source in self.additive_strike_sources)

    @property
    def multiplicative_strike(self) -> tuple[float, ...]:
        return tuple(float(factor) for _, factor in self.multiplicative_strike_sources)

    @property
    def global_condition(self) -> float:
        return sum(float(source.bonus) for source in self.global_condition_sources)

    @property
    def condition_specific(self) -> dict[str, float]:
        return {
            condition: sum(float(source.bonus) for source in sources)
            for condition, sources in self.condition_specific_sources.items()
        }

    @property
    def additive_strike_factor(self) -> float:
        return max(0.0, 1.0 + self.additive_strike)

    @property
    def multiplicative_strike_factor(self) -> float:
        factor = 1.0
        for value in self.multiplicative_strike:
            factor *= max(0.0, float(value))
        return factor

    def condition_factor(self, condition: str) -> float:
        return max(0.0, 1.0 + self.global_condition + self.condition_specific.get(condition, 0.0))

    def condition_sources(self, condition: str) -> tuple[ModifierSource, ...]:
        return self.global_condition_sources + self.condition_specific_sources.get(condition, ())
