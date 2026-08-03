"""Evidence-aware benchmark damage attribution and prediction readiness.

This module deliberately separates three concepts:
- observed: values read directly from Elite Insights;
- attributed: aggregate condition damage distributed across explicit condition packets;
- predicted: independently calculated damage (not available until every required
  stat/modifier/timing input is closed).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

CONDITION_IDS = {
    723: "Poison",
    736: "Bleeding",
    737: "Burning",
    861: "Confusion",
    19426: "Torment",
}


def _skill_name(report: dict[str, Any], skill_id: int) -> str:
    return report.get("skillMap", {}).get(f"s{skill_id}", {}).get("name", f"Skill {skill_id}")


def _cast_counts(report: dict[str, Any]) -> dict[int, int]:
    player = report["players"][0]
    return {int(row["id"]): len(row.get("skills", [])) for row in player.get("rotation", [])}


def _packet_stack_seconds(event: dict[str, Any]) -> float:
    stacks = float(event.get("stacks_per_application", event.get("stacks", 1)) or 1)
    duration = float(event.get("base_duration", event.get("duration", 0)) or 0)
    applications = float(event.get("applications_per_hit", event.get("applications_per_trigger", 1)) or 1)
    repeats = float(event.get("hits", event.get("charges", 1)) or 1)
    return stacks * duration * applications * repeats


def build_condition_attribution(report: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Allocate observed aggregate condition damage using explicit packet weights.

    This is attribution, not independent prediction. It is useful for exposing
    which skill definitions dominate each condition and which observed damage
    remains unsupported by the current event library.
    """
    player = report["players"][0]
    casts = _cast_counts(report)
    observed_by_condition: dict[str, int] = {}
    for row in player.get("targetDamageDist", [[[]]])[0][0]:
        sid = int(row.get("id", 0) or 0)
        if sid in CONDITION_IDS:
            observed_by_condition[CONDITION_IDS[sid]] = int(row.get("totalDamage", 0) or 0)

    weights: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unsupported: list[dict[str, Any]] = []
    for sid, cast_count in casts.items():
        override = overrides.get(str(sid), {})
        events = override.get("condition_events") or []
        if not events:
            continue
        for event_index, event in enumerate(events, start=1):
            condition = str(event.get("condition", "")).strip()
            if condition not in observed_by_condition:
                continue
            per_cast = _packet_stack_seconds(event)
            total_weight = per_cast * cast_count
            if total_weight <= 0:
                unsupported.append({
                    "skill_id": sid,
                    "name": _skill_name(report, sid),
                    "condition": condition,
                    "reason": "Condition event has no positive stack-duration weight",
                })
                continue
            weights[condition].append({
                "skill_id": sid,
                "name": _skill_name(report, sid),
                "event_index": event_index,
                "phase": event.get("phase", "condition_event"),
                "casts": cast_count,
                "base_stack_seconds_per_cast": per_cast,
                "weight": total_weight,
            })

    rows: list[dict[str, Any]] = []
    condition_summary: list[dict[str, Any]] = []
    total_attributed = 0.0
    for condition, observed_damage in observed_by_condition.items():
        condition_rows = weights.get(condition, [])
        total_weight = sum(row["weight"] for row in condition_rows)
        if total_weight <= 0:
            condition_summary.append({
                "condition": condition,
                "observed_damage": observed_damage,
                "attributed_damage": 0,
                "source_coverage": "unmapped",
                "explicit_sources": 0,
            })
            continue
        allocated = 0.0
        for index, row in enumerate(condition_rows):
            share = row["weight"] / total_weight
            damage = observed_damage * share
            if index == len(condition_rows) - 1:
                damage = observed_damage - allocated
            allocated += damage
            total_attributed += damage
            rows.append({
                **row,
                "condition": condition,
                "condition_observed_damage": observed_damage,
                "attribution_share_pct": round(share * 100, 3),
                "attributed_damage": round(damage),
                "attributed_dps": round(damage / (report.get("durationMS", 1) / 1000.0), 2),
                "evidence_status": "estimated_from_explicit_packets",
            })
        condition_summary.append({
            "condition": condition,
            "observed_damage": observed_damage,
            "attributed_damage": round(allocated),
            "source_coverage": "packet-weighted estimate",
            "explicit_sources": len(condition_rows),
        })

    rows.sort(key=lambda row: row["attributed_damage"], reverse=True)
    condition_summary.sort(key=lambda row: row["observed_damage"], reverse=True)
    total_observed_condition = sum(observed_by_condition.values())
    return {
        "summary": {
            "observed_condition_damage": total_observed_condition,
            "attributed_condition_damage": round(total_attributed),
            "attribution_coverage_pct": round(total_attributed / total_observed_condition * 100, 2) if total_observed_condition else 0.0,
            "independent_prediction_ready": False,
            "label": "ATTRIBUTION ESTIMATE — preserves the observed condition total; not independently simulated",
        },
        "conditions": condition_summary,
        "sources": rows,
        "unsupported": unsupported,
        "prediction_blockers": [
            "Per-cast condition application timestamps are not exposed by aggregate Elite Insights condition rows.",
            "Trait-, sigil-, relic-, and artifact-created condition packets are not all explicit in the current event library.",
            "A verified benchmark stat snapshot and complete damage-modifier state must be frozen for independent formulas.",
            "Condition ramp, overlap, target death truncation, and delayed pulses require an event-time simulation rather than stack-second weighting.",
        ],
    }
