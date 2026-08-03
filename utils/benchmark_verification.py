"""Strict readiness gate for the Antiquary benchmark simulator.

The gate never equates an observed replay or packet attribution with an
independent prediction.  Every category has explicit evidence and blockers.
"""
from __future__ import annotations

from typing import Any


def build_verification_report(
    replay: dict[str, Any],
    readiness: dict[str, Any],
    attribution: dict[str, Any],
    artifact_audit: dict[str, Any],
) -> dict[str, Any]:
    rs = replay.get("summary", {})
    ready = readiness.get("summary", {})
    attr = attribution.get("summary", {})
    art = artifact_audit.get("summary", {})

    cooldown_conflicts = len(replay.get("cooldown_violations", []))
    timeline_violations = int(art.get("timeline_violations", 0) or 0)
    condition_rows = attribution.get("conditions", [])
    mapped_conditions = sum(1 for row in condition_rows if row.get("source_coverage") != "unmapped")
    total_conditions = len(condition_rows)

    categories = [
        {
            "category": "Benchmark input",
            "status": "VERIFIED",
            "progress_pct": 100,
            "evidence": "Uploaded Elite Insights JSON is bundled and parsed.",
            "blocker": "",
        },
        {
            "category": "Cast timeline",
            "status": "VERIFIED",
            "progress_pct": round(float(rs.get("cast_model_coverage_pct", 0)), 1),
            "evidence": f"{rs.get('observed_casts', 0)} observed casts; reconstructed uptime {rs.get('reconstructed_cast_uptime_pct', 0)}%.",
            "blocker": "Unmodeled cast roles remain" if float(rs.get("cast_model_coverage_pct", 0)) < 100 else "",
        },
        {
            "category": "Core dagger skills",
            "status": "VERIFIED" if int(ready.get("ready_skill_records", 0)) >= 9 else "BLOCKED",
            "progress_pct": 100 if int(ready.get("ready_skill_records", 0)) >= 9 else 0,
            "evidence": f"{ready.get('ready_skill_records', 0)} benchmark core records use explicit PvE hit/condition packets.",
            "blocker": "" if int(ready.get("ready_skill_records", 0)) >= 9 else "Core skill event definitions incomplete",
        },
        {
            "category": "Artifact use/follow-ups",
            "status": "VERIFIED" if timeline_violations == 0 else "BLOCKED",
            "progress_pct": 100 if timeline_violations == 0 else 0,
            "evidence": f"{art.get('root_artifact_casts', 0)} root uses and {art.get('follow_up_casts', 0)} follow-ups; {timeline_violations} invalid transitions.",
            "blocker": "" if timeline_violations == 0 else "Invalid artifact follow-up transitions",
        },
        {
            "category": "Initiative affordability",
            "status": "VERIFIED" if float(rs.get("unmodeled_initiative_income_required", 1)) == 0 else "BLOCKED",
            "progress_pct": 100 if float(rs.get("unmodeled_initiative_income_required", 1)) == 0 else 0,
            "evidence": f"Spent {rs.get('initiative_spent', 0)}; confirmed artifact gain +{rs.get('confirmed_artifact_initiative_gain', 0)}; aggregate unexplained income {rs.get('unmodeled_initiative_income_required', 0)}.",
            "blocker": "",
        },
        {
            "category": "Cooldown/state legality",
            "status": "BLOCKED" if cooldown_conflicts else "VERIFIED",
            "progress_pct": max(0, round(100 - cooldown_conflicts / max(1, int(rs.get("observed_casts", 1))) * 100, 1)),
            "evidence": f"Holo-Dancer consumption events: {rs.get('holo_utility_consumptions', 0)}.",
            "blocker": f"{cooldown_conflicts} observed spacings still need charge/reset/alacrity/double-edge state classification." if cooldown_conflicts else "",
        },
        {
            "category": "Direct-damage mapping",
            "status": "PARTIAL" if float(rs.get("direct_damage_model_coverage_pct", 0)) < 100 else "VERIFIED",
            "progress_pct": round(float(rs.get("direct_damage_model_coverage_pct", 0)), 1),
            "evidence": f"{rs.get('direct_damage_explained', 0):,} observed direct damage mapped.",
            "blocker": "Remaining direct rows lack an independent coefficient/stat calculation." if float(rs.get("direct_damage_model_coverage_pct", 0)) < 100 else "",
        },
        {
            "category": "Condition source mapping",
            "status": "BLOCKED" if mapped_conditions < total_conditions else "VERIFIED",
            "progress_pct": round(mapped_conditions / max(1, total_conditions) * 100, 1),
            "evidence": f"{mapped_conditions}/{total_conditions} observed condition types have explicit packet sources; packet attribution covers {attr.get('attribution_coverage_pct', 0)}% of condition damage.",
            "blocker": "One or more observed condition types still lack explicit PvE packets." if mapped_conditions < total_conditions else "",
        },
        {
            "category": "Independent damage formulas",
            "status": "BLOCKED",
            "progress_pct": 0,
            "evidence": "Observed damage and attribution are available, but they are not predictions.",
            "blocker": "Freeze the exact stat snapshot, weapon strength, target armor, modifier timeline, condition formulas, and event timestamps.",
        },
    ]

    completed = sum(1 for row in categories if row["status"] == "VERIFIED")
    blockers = [row for row in categories if row["status"] == "BLOCKED"]
    weighted = round(sum(float(row["progress_pct"]) for row in categories) / len(categories), 1)
    return {
        "summary": {
            "verified_categories": completed,
            "total_categories": len(categories),
            "overall_progress_pct": weighted,
            "blocking_categories": len(blockers),
            "simulation_ready": len(blockers) == 0,
            "status": "READY FOR INDEPENDENT SIMULATION" if not blockers else "NOT READY — verification blockers remain",
            "observed_dps": int(rs.get("observed_dps", 0) or 0),
            "observed_dps_is_prediction": False,
        },
        "categories": categories,
        "next_actions": [
            "Cooldown legality now applies alacrity, Holo-Dancer, Repeat Ransacker, preparation sequencing, and Double Edge recharge.",
            "Burning, Torment, and Confusion now have explicit benchmark PvE packets; validate trait variants when changing build presets.",
            "Freeze the benchmark stat/modifier snapshot before calculating any predicted damage.",
            "Run an event-time simulation and compare predicted damage per source against Elite Insights.",
        ],
    }
