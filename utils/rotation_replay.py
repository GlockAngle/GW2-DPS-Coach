"""Observed rotation replay and benchmark-comparison helpers.

This is intentionally a replay engine, not yet a free-form optimizer. It rebuilds
an Elite Insights cast timeline, validates cooldown/state constraints, estimates
initiative pressure from verified costs, and reports exactly which parts of the
benchmark can be explained by the current skill library.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

from utils.antiquary_artifacts import DEFINITIONS
from utils.antiquary_mechanics import (
    ARTIFACT_SKILL_IDS,
    BENCHMARK_UTILITY_IDS,
    HOLO_DANCER_ID,
    MECHANICS,
    mechanics_rows,
)

CONDITION_IDS = {723, 736, 737, 861, 19426}
CORE_READY_IDS = {13004, 13005, 13006, 13026, 13028, 13037, 13087, 13108, 56898}


@dataclass(frozen=True)
class ReplayConfig:
    initial_initiative: float = 15.0
    max_initiative: float = 15.0
    initiative_regen_per_second: float = 1.0


def _skill_name(report: dict[str, Any], skill_id: int) -> str:
    return report.get("skillMap", {}).get(f"s{skill_id}", {}).get("name", f"Skill {skill_id}")


def _load_overrides(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def _damage_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    player = report["players"][0]
    return list(player.get("targetDamageDist", [[[]]])[0][0])


def build_rotation_replay(
    report: dict[str, Any],
    overrides: dict[str, Any],
    config: ReplayConfig | None = None,
) -> dict[str, Any]:
    config = config or ReplayConfig()
    player = report["players"][0]
    duration_ms = int(report.get("durationMS", 0) or 0)

    timeline: list[dict[str, Any]] = []
    for rotation_row in player.get("rotation", []):
        sid = int(rotation_row["id"])
        name = _skill_name(report, sid)
        override = overrides.get(str(sid), {})
        role = "artifact" if sid in ARTIFACT_SKILL_IDS else "core" if sid in CORE_READY_IDS else "other"
        for cast in rotation_row.get("skills", []):
            start = int(cast.get("castTime", 0) or 0)
            duration = max(0, int(cast.get("duration", 0) or 0))
            timeline.append({
                "time_ms": start,
                "end_ms": start + duration,
                "duration_ms": duration,
                "skill_id": sid,
                "name": name,
                "role": role,
                "initiative_cost": float(override.get("initiative_cost", 0) or 0),
                "recharge_s": float(override.get("recharge_override", override.get("recharge", 0)) or 0),
                "ready_model": sid in CORE_READY_IDS or sid in ARTIFACT_SKILL_IDS,
            })
    timeline.sort(key=lambda row: (row["time_ms"], row["skill_id"]))

    # Build a stateful recharge timeline. The benchmark profile has 100%
    # alacrity, Holo-Dancer modifies the next utility recharge, and Repeat
    # Ransacker removes two seconds from Skritt Swipe whenever an artifact is used.
    holo_expires_ms: int | None = None
    holo_reduction = float(MECHANICS["holo_utility_recharge_reduction"].value) / 100.0
    holo_duration_ms = int(float(MECHANICS["holo_effect_duration"].value) * 1000)
    alacrity_factor = float(MECHANICS["benchmark_alacrity_recharge_factor"].value)
    repeat_ransacker_ms = int(float(MECHANICS["repeat_ransacker_recharge_reduction"].value) * 1000)
    holo_consumptions: list[dict[str, Any]] = []
    cooldown_adjustments: list[dict[str, Any]] = []
    ready_at: dict[int, int] = {}
    cooldown_violations: list[dict[str, Any]] = []

    for row in timeline:
        at = row["time_ms"]
        sid = row["skill_id"]

        # Artifact use reduces the currently remaining Skritt Swipe recharge.
        if sid in ARTIFACT_SKILL_IDS and 77397 in ready_at and ready_at[77397] > at:
            before = ready_at[77397]
            ready_at[77397] = max(at, before - repeat_ransacker_ms)
            cooldown_adjustments.append({
                "time_ms": at, "source": row["name"], "target": "Skritt Swipe",
                "kind": "Repeat Ransacker", "before_ready_ms": before,
                "after_ready_ms": ready_at[77397], "reduction_ms": before - ready_at[77397],
            })

        if sid == HOLO_DANCER_ID:
            holo_expires_ms = at + holo_duration_ms
            row["state_effect"] = "arms_holo_utility_recharge"

        effective = float(row["recharge_s"]) * alacrity_factor if row["recharge_s"] else 0.0
        row["recharge_after_alacrity_s"] = effective

        if (holo_expires_ms is not None and at <= holo_expires_ms and sid in BENCHMARK_UTILITY_IDS):
            before_holo = effective
            effective *= (1.0 - holo_reduction)
            row["state_effect"] = "consumes_holo_utility_recharge"
            holo_consumptions.append({
                "time_ms": at, "skill_id": sid, "name": row["name"],
                "base_recharge_s": row["recharge_s"],
                "alacrity_recharge_s": before_holo,
                "effective_recharge_s": effective,
            })
            holo_expires_ms = None
        else:
            row.setdefault("state_effect", "")

        row["effective_recharge_s"] = effective
        required_ready = ready_at.get(sid, -10**9)
        if at + 50 < required_ready:
            cooldown_violations.append({
                "skill_id": sid, "name": row["name"], "time_ms": at,
                "elapsed_to_ready_ms": at - required_ready,
                "required_ready_ms": required_ready,
                "remaining_ms": required_ready - at,
            })
        if effective > 0:
            ready_at[sid] = at + int(round(effective * 1000))

    # Merge overlapping observed action intervals to measure actual occupied timeline.
    intervals = sorted((max(0, r["time_ms"]), min(duration_ms, r["end_ms"])) for r in timeline if r["duration_ms"] > 0)
    merged: list[list[int]] = []
    for start, end in intervals:
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    busy_ms = sum(end - start for start, end in merged)

    gaps: list[dict[str, Any]] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            gaps.append({"start_ms": cursor, "end_ms": start, "duration_ms": start - cursor})
        cursor = max(cursor, end)
    if cursor < duration_ms:
        gaps.append({"start_ms": cursor, "end_ms": duration_ms, "duration_ms": duration_ms - cursor})
    meaningful_gaps = [g for g in gaps if g["duration_ms"] >= 250]

    # Initiative replay with confirmed PvE Antiquary income.
    initiative = config.initial_initiative
    last_time = 0
    minimum = initiative
    spent = 0.0
    confirmed_gained = 0.0
    ledger: list[dict[str, Any]] = []
    artifact_gain = float(MECHANICS["artifact_initiative_gain"].value)
    for row in timeline:
        at = max(0, row["time_ms"])
        passive_gain = ((at - last_time) / 1000.0) * config.initiative_regen_per_second
        initiative = min(config.max_initiative, initiative + passive_gain)

        if row["skill_id"] in ARTIFACT_SKILL_IDS:
            before_gain = initiative
            initiative = min(config.max_initiative, initiative + artifact_gain)
            actual_gain = initiative - before_gain
            confirmed_gained += actual_gain
            ledger.append({
                "time_ms": at,
                "skill_id": row["skill_id"],
                "name": row["name"],
                "event": "artifact_gain",
                "before": round(before_gain, 3),
                "gain": round(actual_gain, 3),
                "after": round(initiative, 3),
            })

        cost = row["initiative_cost"]
        before = initiative
        initiative -= cost
        spent += cost
        minimum = min(minimum, initiative)
        if cost:
            ledger.append({
                "time_ms": at,
                "skill_id": row["skill_id"],
                "name": row["name"],
                "event": "spend",
                "before": round(before, 3),
                "cost": cost,
                "after": round(initiative, 3),
            })
        last_time = at
    passive_available = config.initial_initiative + duration_ms / 1000.0 * config.initiative_regen_per_second
    confirmed_available = passive_available + confirmed_gained
    unmodeled_income_required = max(0.0, spent - confirmed_available)

    # Damage coverage is evidence-based: aggregate conditions remain unattributed.
    damage_rows = _damage_rows(report)
    total_damage = int(player.get("dpsAll", [{}])[0].get("damage", 0) or 0)
    total_power = int(player.get("dpsAll", [{}])[0].get("powerDamage", 0) or 0)
    total_condi = int(player.get("dpsAll", [{}])[0].get("condiDamage", 0) or 0)
    damage_table: list[dict[str, Any]] = []
    explained_direct = 0
    for row in damage_rows:
        sid = int(row.get("id", 0) or 0)
        damage = int(row.get("totalDamage", 0) or 0)
        is_condition = sid in CONDITION_IDS
        model_status = (
            "aggregate_condition_unattributed" if is_condition
            else "modeled_cast_or_artifact" if sid in CORE_READY_IDS or sid in ARTIFACT_SKILL_IDS or sid in {78440, 77028, 76816}
            else "unmodeled_damage_source"
        )
        if model_status == "modeled_cast_or_artifact":
            explained_direct += damage
        damage_table.append({
            "skill_id": sid,
            "name": _skill_name(report, sid),
            "damage": damage,
            "hits": int(row.get("connectedHits", 0) or 0),
            "model_status": model_status,
            "share_pct": round(damage / total_damage * 100, 3) if total_damage else 0,
        })
    damage_table.sort(key=lambda r: r["damage"], reverse=True)

    observed_casts = len(timeline)
    modeled_casts = sum(1 for row in timeline if row["ready_model"])
    stats = player.get("statsAll", [{}])[0]
    return {
        "summary": {
            "fight_duration_ms": duration_ms,
            "observed_dps": int(player.get("dpsAll", [{}])[0].get("dps", 0) or 0),
            "observed_damage": total_damage,
            "observed_power_damage": total_power,
            "observed_condition_damage": total_condi,
            "observed_casts": observed_casts,
            "modeled_casts": modeled_casts,
            "cast_model_coverage_pct": round(modeled_casts / observed_casts * 100, 2) if observed_casts else 0,
            "busy_time_ms": busy_ms,
            "reconstructed_cast_uptime_pct": round(busy_ms / duration_ms * 100, 3) if duration_ms else 0,
            "elite_insights_cast_uptime_pct": float(stats.get("skillCastUptime", 0) or 0),
            "meaningful_gaps": len(meaningful_gaps),
            "cooldown_violations": len(cooldown_violations),
            "initiative_spent": round(spent, 3),
            "minimum_passive_only_initiative": round(minimum, 3),
            "confirmed_artifact_initiative_gain": round(confirmed_gained, 3),
            "unmodeled_initiative_income_required": round(unmodeled_income_required, 3),
            "damage_profile": "Benchmark boons/conditions from the uploaded golem log; player damage only, no allied damage added",
            "dps_label_status": "OBSERVED FROM LOG — not an independently predicted DPS value",
            "holo_utility_consumptions": len(holo_consumptions),
            "direct_damage_explained": explained_direct,
            "direct_damage_model_coverage_pct": round(explained_direct / total_power * 100, 2) if total_power else 0,
            "rotation_engine_status": "COOLDOWN-CALIBRATED REPLAY — observed timeline only; independent damage prediction remains separate",
        },
        "timeline": timeline,
        "gaps": meaningful_gaps,
        "cooldown_violations": cooldown_violations,
        "initiative_ledger": ledger,
        "damage_comparison": damage_table,
        "holo_utility_consumptions": holo_consumptions,
        "cooldown_adjustments": cooldown_adjustments,
        "mechanics": mechanics_rows(),
        "limitations": [
            "Condition damage rows are aggregate Elite Insights outputs and are not assigned back to individual casts without combat-event evidence.",
            "Enterprising Aristocrat now grants the verified PvE artifact-use initiative gain. Any remaining deficit is still exposed rather than invented.",
            "Artifact use is replayed from observed casts. Hidden random grant timestamps remain external state inputs.",
            "This build replays the benchmark timeline; it does not yet generate an optimized rotation from scratch.",
        ],
    }


def load_and_build(report_path: str | Path, overrides_path: str | Path) -> dict[str, Any]:
    with Path(report_path).open(encoding="utf-8") as handle:
        report = json.load(handle)
    return build_rotation_replay(report, _load_overrides(overrides_path))
