from __future__ import annotations

from dataclasses import asdict, dataclass, field
try:
    from enum import StrEnum
except ImportError:  # Python 3.10 and older
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from typing import Any, Iterable


class EffectKind(StrEnum):
    """How an effect changes the shared calculator state."""

    STAT_ADD = "stat_add"
    MODIFIER_ADD = "modifier_add"
    CONVERSION = "conversion"


@dataclass(frozen=True)
class RegisteredEffect:
    source: str
    target: str
    value: float
    kind: EffectKind
    source_id: int | None = None
    destination: str = ""
    condition: str = "Always"
    active: bool = True
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["kind"] = self.kind.value
        return row


@dataclass
class EffectRegistry:
    """Central source-of-truth for active build effects.

    Pages and future skill modules register effects here. The compatibility
    adapter returns the legacy stat/modifier dictionaries used by the current
    damage engine, so the UI can be migrated without changing formulas.
    """

    effects: list[RegisteredEffect] = field(default_factory=list)

    def register(self, effect: RegisteredEffect) -> None:
        if not effect.active or abs(float(effect.value)) < 1e-12:
            return
        self.effects.append(effect)

    def register_stat(
        self,
        source: str,
        target: str,
        value: float,
        *,
        source_id: int | None = None,
        destination: str = "Resulting stats",
        condition: str = "Always",
        note: str = "",
    ) -> None:
        self.register(RegisteredEffect(source, target, float(value), EffectKind.STAT_ADD, source_id, destination, condition, True, note))

    def register_modifier(
        self,
        source: str,
        target: str,
        value: float,
        *,
        source_id: int | None = None,
        destination: str = "Damage engine",
        condition: str = "Always",
        note: str = "",
    ) -> None:
        self.register(RegisteredEffect(source, target, float(value), EffectKind.MODIFIER_ADD, source_id, destination, condition, True, note))

    def register_conversion(
        self,
        source: str,
        target: str,
        value: float,
        *,
        source_id: int | None = None,
        destination: str = "Resulting stats",
        condition: str = "Always",
        note: str = "",
    ) -> None:
        self.register(RegisteredEffect(source, target, float(value), EffectKind.CONVERSION, source_id, destination, condition, True, note))

    def totals(self, kind: EffectKind) -> dict[str, float]:
        result: dict[str, float] = {}
        for effect in self.effects:
            if effect.kind == kind:
                result[effect.target] = result.get(effect.target, 0.0) + effect.value
        return result

    def to_legacy(self) -> tuple[dict[str, float], dict[str, float]]:
        stats = self.totals(EffectKind.STAT_ADD)
        modifiers = self.totals(EffectKind.MODIFIER_ADD)
        for target, value in self.totals(EffectKind.CONVERSION).items():
            modifiers[target] = modifiers.get(target, 0.0) + value
        return stats, modifiers

    def for_target(self, target: str, kinds: Iterable[EffectKind] | None = None) -> list[RegisteredEffect]:
        allowed = set(kinds) if kinds is not None else None
        return [
            effect for effect in self.effects
            if effect.target == target and (allowed is None or effect.kind in allowed)
        ]

    def serialize(self) -> list[dict[str, Any]]:
        return [effect.as_dict() for effect in self.effects]

    @classmethod
    def deserialize(cls, rows: list[dict[str, Any]] | None) -> "EffectRegistry":
        registry = cls()
        for row in rows or []:
            try:
                registry.register(RegisteredEffect(
                    source=str(row.get("source", "Unknown")),
                    target=str(row.get("target", "")),
                    value=float(row.get("value", 0.0)),
                    kind=EffectKind(str(row.get("kind", EffectKind.MODIFIER_ADD.value))),
                    source_id=int(row["source_id"]) if row.get("source_id") is not None else None,
                    destination=str(row.get("destination", "")),
                    condition=str(row.get("condition", "Always")),
                    active=bool(row.get("active", True)),
                    note=str(row.get("note", "")),
                ))
            except (TypeError, ValueError):
                continue
        return registry
