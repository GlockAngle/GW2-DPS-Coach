"""Antiquary artifact state and benchmark validation helpers.

This module deliberately separates observed Elite Insights facts from mechanics that
cannot be reconstructed from the JSON alone.  It is safe to use for benchmark
validation and later as the state container for a rotation simulator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import random


from utils.antiquary_mechanics import ARTIFACT_SKILL_IDS

ARTIFACT_CHILD_IDS = {78440, 77028, 76816}


@dataclass(frozen=True)
class ArtifactDefinition:
    skill_id: int
    name: str
    family: str
    role: str
    child_effect_ids: tuple[int, ...] = ()
    follow_up_ids: tuple[int, ...] = ()
    follow_up_charges: int = 1
    notes: str = ""


DEFINITIONS: dict[int, ArtifactDefinition] = {
    76633: ArtifactDefinition(76633, "Forged Surfer Dash", "Forged Surfer", "offensive", (78440,), notes="Dash plus a delayed bomb trail."),
    77277: ArtifactDefinition(77277, "Mistburn Mortar", "Mistburn Mortar", "offensive", notes="Multi-hit offensive artifact."),
    77192: ArtifactDefinition(77192, "Summon Kryptis Turret", "Kryptis Turret", "offensive", notes="Persistent turret with a variable number of attacks before expiry or fight end."),
    76674: ArtifactDefinition(76674, "Holo-Dancer Decoy", "Holo-Dancer", "offensive", (77028,), notes="The cast and its decoy damage are separate log rows."),
    76582: ArtifactDefinition(76582, "Metal Legion Guitar (Rockout)", "Metal Legion Guitar", "channel", follow_up_ids=(76596,), notes="Channel/pulse phase; Smash is a separate follow-up skill."),
    76596: ArtifactDefinition(76596, "Metal Legion Guitar (Smash)", "Metal Legion Guitar", "follow_up", notes="Finisher for Rockout, not a separate artifact roll."),
    76895: ArtifactDefinition(76895, "Zephyrite Sun Crystal", "Zephyrite Sun Crystal", "offensive", (76816,), notes="Observed with a separate Chak Shield child damage source in this benchmark."),
}


@dataclass
class ArtifactState:
    held: list[int] = field(default_factory=list)
    follow_up_charges: dict[int, int] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def grant(self, artifact_id: int, at_ms: int, source: str = "unknown") -> None:
        if artifact_id not in DEFINITIONS or DEFINITIONS[artifact_id].role == "follow_up":
            raise ValueError(f"{artifact_id} is not a grantable root artifact")
        self.held.append(artifact_id)
        self.history.append({"time_ms": at_ms, "event": "grant", "skill_id": artifact_id, "source": source})

    def consume(self, artifact_id: int, at_ms: int) -> None:
        if artifact_id not in self.held:
            raise ValueError(f"Artifact {artifact_id} is not currently held")
        self.held.remove(artifact_id)
        definition = DEFINITIONS[artifact_id]
        for follow_up in definition.follow_up_ids:
            self.follow_up_charges[follow_up] = self.follow_up_charges.get(follow_up, 0) + definition.follow_up_charges
        self.history.append({"time_ms": at_ms, "event": "consume", "skill_id": artifact_id})

    def use_follow_up(self, skill_id: int, at_ms: int) -> None:
        available = self.follow_up_charges.get(skill_id, 0)
        if available <= 0:
            raise ValueError(f"Follow-up {skill_id} has no available charge")
        self.follow_up_charges[skill_id] = available - 1
        self.history.append({"time_ms": at_ms, "event": "follow_up", "skill_id": skill_id})


def draw_artifact(rng: random.Random | None = None, *, include_setup: bool = True) -> int:
    """Draw one root artifact. This models selection only; real generation timing is external."""
    rng = rng or random.Random()
    pool = [sid for sid, item in DEFINITIONS.items() if item.role in ({"offensive", "setup", "channel"} if include_setup else {"offensive", "channel"})]
    return rng.choice(sorted(pool))


def _skill_name(report: dict[str, Any], skill_id: int) -> str:
    return report.get("skillMap", {}).get(f"s{skill_id}", {}).get("name", f"Skill {skill_id}")


def _rotation_rows(report: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    player = report["players"][0]
    return {int(row["id"]): list(row.get("skills", [])) for row in player.get("rotation", [])}


def _damage_rows(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    player = report["players"][0]
    # Elite Insights repeats cumulative phase rows. The first target of the first phase is the full-fight row.
    full_rows = player.get("targetDamageDist", [[[]]])[0][0]
    return {int(row["id"]): row for row in full_rows}


def build_benchmark_artifact_audit(report: dict[str, Any]) -> dict[str, Any]:
    rotations = _rotation_rows(report)
    damages = _damage_rows(report)
    records: list[dict[str, Any]] = []

    for skill_id, definition in DEFINITIONS.items():
        casts = rotations.get(skill_id, [])
        damage = damages.get(skill_id, {})
        child_rows = []
        for child_id in definition.child_effect_ids:
            row = damages.get(child_id, {})
            child_rows.append({
                "id": child_id,
                "name": _skill_name(report, child_id),
                "hits": int(row.get("connectedHits", 0) or 0),
                "damage": int(row.get("totalDamage", 0) or 0),
            })
        duration_values = [int(c.get("duration", 0) or 0) for c in casts]
        records.append({
            "id": skill_id,
            "name": definition.name,
            "family": definition.family,
            "role": definition.role,
            "casts": len(casts),
            "cast_times_ms": [int(c.get("castTime", 0) or 0) for c in casts],
            "median_action_ms": sorted(duration_values)[len(duration_values)//2] if duration_values else None,
            "direct_hits": int(damage.get("connectedHits", 0) or 0),
            "direct_damage": int(damage.get("totalDamage", 0) or 0),
            "observed_direct_hits_per_cast": round((int(damage.get("connectedHits", 0) or 0) / len(casts)), 3) if casts else None,
            "children": child_rows,
            "follow_up_ids": list(definition.follow_up_ids),
            "notes": definition.notes,
            "verification": "benchmark_observed" if casts else "not_observed",
        })

    # Validate follow-up ordering from the observed cast timeline.
    timeline = []
    for sid, casts in rotations.items():
        if sid in ARTIFACT_SKILL_IDS:
            for cast in casts:
                timeline.append((int(cast.get("castTime", 0)), sid))
    timeline.sort()
    active_followups: dict[int, int] = {}
    violations: list[str] = []
    for at_ms, sid in timeline:
        definition = DEFINITIONS[sid]
        if definition.role == "follow_up":
            if active_followups.get(sid, 0) <= 0:
                violations.append(f"{definition.name} at {at_ms} ms had no observed parent setup in the reconstructed timeline")
            else:
                active_followups[sid] -= 1
        else:
            for follow_up in definition.follow_up_ids:
                active_followups[follow_up] = active_followups.get(follow_up, 0) + definition.follow_up_charges

    root_casts = sum(r["casts"] for r in records if r["role"] != "follow_up")
    follow_up_casts = sum(r["casts"] for r in records if r["role"] == "follow_up")
    return {
        "summary": {
            "fight_duration_ms": int(report.get("durationMS", 0) or 0),
            "root_artifact_casts": root_casts,
            "follow_up_casts": follow_up_casts,
            "artifact_families_observed": len({r["family"] for r in records if r["casts"]}),
            "timeline_violations": len(violations),
            "rotation_engine_status": "ARTIFACT EVENTS READY; generation probabilities/timing remain an explicit external input",
            "important_limit": "Elite Insights records artifact use and damage, but does not prove the hidden random roll or inventory grant event. The engine therefore never invents generation timestamps.",
        },
        "records": records,
        "timeline": [{"time_ms": t, "skill_id": sid, "name": DEFINITIONS[sid].name, "role": DEFINITIONS[sid].role} for t, sid in timeline],
        "violations": violations,
    }


def load_and_audit(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return build_benchmark_artifact_audit(json.load(handle))
