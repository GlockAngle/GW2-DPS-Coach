"""Generic, auditable combat-engine foundation."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any
from .damage_engine import DamageModifiers, calculate_condition_damage, calculate_strike_damage

@dataclass(frozen=True)
class CharacterSnapshot:
    power: float
    condition_damage: float
    precision: float = 1000.0
    ferocity: float = 0.0
    weapon_strength: float = 1000.0
    enemy_armor: float = 2597.0
    vulnerability_stacks: int = 25
    critical_chance: float | None = None
    critical_damage: float | None = None
    modifiers: DamageModifiers = field(default_factory=DamageModifiers)

    def resolved_critical_chance(self) -> float:
        if self.critical_chance is not None:
            return min(1.0, max(0.0, float(self.critical_chance)))
        return min(1.0, max(0.0, (float(self.precision) - 1000.0) / 2100.0 + 0.05))

    def resolved_critical_damage(self) -> float:
        if self.critical_damage is not None:
            return max(1.0, float(self.critical_damage))
        return 1.5 + max(0.0, float(self.ferocity)) / 1500.0

    def missing_required_fields(self) -> list[str]:
        return [name for name in ("power", "condition_damage", "weapon_strength", "enemy_armor") if float(getattr(self, name, 0) or 0) <= 0]

    def audit_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("modifiers", None)
        data["resolved_critical_chance"] = self.resolved_critical_chance()
        data["resolved_critical_damage"] = self.resolved_critical_damage()
        return data

@dataclass(frozen=True)
class StrikeEvent:
    name: str
    coefficient: float
    hits: int = 1

@dataclass(frozen=True)
class ConditionEvent:
    name: str
    condition: str
    stacks: float
    duration_s: float
    applications: int = 1

def simulate_strike_event(snapshot: CharacterSnapshot, event: StrikeEvent) -> dict[str, Any]:
    per_hit = calculate_strike_damage(power=snapshot.power, weapon_strength=snapshot.weapon_strength, coefficient=event.coefficient, enemy_armor=snapshot.enemy_armor, critical_chance=snapshot.resolved_critical_chance(), critical_damage=snapshot.resolved_critical_damage(), vulnerability_stacks=snapshot.vulnerability_stacks, modifiers=snapshot.modifiers)
    hits = max(0, int(event.hits))
    return {"event": event.name, "event_type": "strike", "hits": hits, "coefficient_per_hit": float(event.coefficient), "expected_damage_per_hit": per_hit["expected_hit"], "expected_total_damage": per_hit["expected_hit"] * hits, "formula_audit": per_hit}

def simulate_condition_event(snapshot: CharacterSnapshot, event: ConditionEvent) -> dict[str, Any]:
    rows = calculate_condition_damage(condition_damage=snapshot.condition_damage, vulnerability_stacks=snapshot.vulnerability_stacks, modifiers=snapshot.modifiers)
    key = {"Torment": "Torment (stationary)", "Confusion": "Confusion (tick)"}.get(event.condition, event.condition)
    if key not in rows:
        raise ValueError(f"Unsupported condition: {event.condition}")
    per_stack_second = float(rows[key]["final_damage"])
    stack_seconds = max(0.0, float(event.stacks)) * max(0.0, float(event.duration_s)) * max(0, int(event.applications))
    return {"event": event.name, "event_type": "condition", "condition": event.condition, "applications": max(0, int(event.applications)), "stacks_per_application": max(0.0, float(event.stacks)), "duration_s": max(0.0, float(event.duration_s)), "stack_seconds": stack_seconds, "damage_per_stack_second": per_stack_second, "expected_total_damage": per_stack_second * stack_seconds, "formula_audit": rows[key]}

def engine_readiness(snapshot: CharacterSnapshot, *, timeline_complete: bool, modifiers_complete: bool) -> dict[str, Any]:
    blockers = [f"Missing or invalid profile field: {name}" for name in snapshot.missing_required_fields()]
    if not timeline_complete:
        blockers.append("Complete event timeline is not available")
    if not modifiers_complete:
        blockers.append("Complete trait, relic, sigil and encounter modifier set is not frozen")
    return {"ready_for_total_prediction": not blockers, "blockers": blockers, "snapshot": snapshot.audit_dict(), "rule": "A total predicted DPS value may only be shown when this gate is ready."}
