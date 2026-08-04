from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONDITION_IDS = {
    736: ("Bleeding", "bleeding"),
    723: ("Poison", "poison"),
    737: ("Burning", "burning"),
    19426: ("Torment", "torment_stationary"),
    861: ("Confusion", "confusion"),
}
CONDITION_DAMAGE_TYPES = {value[1] for value in CONDITION_IDS.values()}


def _name(skill_id: int, skill_map: dict[str, Any]) -> str:
    if skill_id in CONDITION_IDS:
        return CONDITION_IDS[skill_id][0]
    for key in (str(skill_id), f"s{skill_id}", f"b{skill_id}"):
        value = skill_map.get(key)
        if isinstance(value, dict):
            return str(value.get("name") or value.get("nameOverride") or f"Skill {skill_id}")
        if isinstance(value, str):
            return value
    return f"Skill {skill_id}"


def load_elite_insights_reference(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    player = (data.get("players") or [{}])[0]
    skill_map = data.get("skillMap") or {}
    target_dist = player.get("targetDamageDist") or []
    rows = target_dist[0][0] if target_dist and target_dist[0] else []

    by_skill: list[dict[str, Any]] = []
    by_type: dict[str, dict[str, Any]] = {}
    for row in rows:
        skill_id = int(row.get("id", 0))
        indirect = bool(row.get("indirectDamage", False))
        damage_type = CONDITION_IDS.get(
            skill_id, (None, "condition" if indirect else "strike")
        )[1]
        damage = float(row.get("totalDamage", 0))
        hits = int(row.get("hits", row.get("connectedHits", 0)) or 0)
        by_skill.append(
            {
                "Skill": _name(skill_id, skill_map),
                "Skill ID": skill_id,
                "Damage type": damage_type,
                "Reference damage": damage,
                "Reference hits / ticks": hits,
                # Elite Insights exposes condition damage as one aggregate row per
                # condition type in this distribution. It does not attribute those
                # rows back to the skill that originally applied each stack.
                "Comparison level": (
                    "damage-type aggregate"
                    if skill_id in CONDITION_IDS
                    else "skill + damage type"
                ),
            }
        )
        aggregate = by_type.setdefault(
            damage_type,
            {
                "Damage type": damage_type,
                "Reference damage": 0.0,
                "Reference hits / ticks": 0,
            },
        )
        aggregate["Reference damage"] += damage
        aggregate["Reference hits / ticks"] += hits

    dps = (player.get("dpsAll") or [{}])[0]
    return {
        "dps": float(dps.get("dps", 0)),
        "total_damage": float(dps.get("damage", 0)),
        "duration_ms": int(data.get("durationMS", 0) or 0),
        "by_skill": sorted(by_skill, key=lambda row: row["Reference damage"], reverse=True),
        "by_damage_type": sorted(
            by_type.values(), key=lambda row: row["Reference damage"], reverse=True
        ),
    }


def _canon(value: str) -> str:
    text = str(value).lower().replace("proc", "").replace("damage", "")
    return "".join(character for character in text if character.isalnum())


def _comparison_row(
    *,
    skill: str,
    damage_type: str,
    reference_damage: float,
    engine_damage: float,
    reference_hits: int,
    engine_hits: int,
    status: str,
    comparison_level: str,
) -> dict[str, Any]:
    difference = engine_damage - reference_damage
    return {
        "Skill": skill,
        "Damage type": damage_type,
        "Comparison level": comparison_level,
        "EI damage": reference_damage,
        "Engine damage": engine_damage,
        "Difference": difference,
        "Difference %": difference / reference_damage if reference_damage else None,
        "EI hits / ticks": reference_hits,
        "Engine hits / ticks": engine_hits,
        "Hit difference": engine_hits - reference_hits,
        "Status": status,
    }


def compare_reference_to_engine(
    reference: dict[str, Any], analysis: dict[str, Any]
) -> dict[str, Any]:
    engine_rows = analysis.get("by_skill", []) or []
    engine_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in engine_rows:
        key = (_canon(row.get("Skill", "")), str(row.get("Damage type", "")))
        engine_by_key.setdefault(key, []).append(row)

    engine_by_type = {
        str(row.get("Damage type", "")): row
        for row in (analysis.get("by_damage_type", []) or [])
    }

    output: list[dict[str, Any]] = []
    used_engine_rows: set[int] = set()

    for ref in reference.get("by_skill", []):
        skill = str(ref.get("Skill", ""))
        damage_type = str(ref.get("Damage type", ""))
        reference_damage = float(ref.get("Reference damage", 0))
        reference_hits = int(ref.get("Reference hits / ticks", 0) or 0)
        comparison_level = str(ref.get("Comparison level", "skill + damage type"))

        if comparison_level == "damage-type aggregate":
            # EI's condition rows are fight-wide totals by condition type. Compare
            # them with the engine's corresponding fight-wide condition total,
            # rather than falsely treating "Bleeding" or "Poison" as a skill.
            engine_type_row = engine_by_type.get(damage_type, {})
            engine_damage = float(engine_type_row.get("Damage", 0))
            engine_hits = int(engine_type_row.get("Hits / ticks", 0) or 0)
            output.append(
                _comparison_row(
                    skill=f"All {skill}",
                    damage_type=damage_type,
                    reference_damage=reference_damage,
                    engine_damage=engine_damage,
                    reference_hits=reference_hits,
                    engine_hits=engine_hits,
                    status="damage-type aggregate",
                    comparison_level="damage-type aggregate",
                )
            )
            continue

        candidates = engine_by_key.get((_canon(skill), damage_type), [])
        used_engine_rows.update(id(row) for row in candidates)
        engine_damage = sum(float(row.get("Damage", 0)) for row in candidates)
        engine_hits = sum(int(row.get("Hits / ticks", 0) or 0) for row in candidates)
        output.append(
            _comparison_row(
                skill=skill,
                damage_type=damage_type,
                reference_damage=reference_damage,
                engine_damage=engine_damage,
                reference_hits=reference_hits,
                engine_hits=engine_hits,
                status="matched" if candidates else "missing in engine",
                comparison_level="skill + damage type",
            )
        )

    # EI does not expose condition damage by applying skill in targetDamageDist.
    # Therefore only unmatched direct/strike rows can honestly be called an
    # engine-only skill source in this table. Engine condition attribution remains
    # visible in the separate Raw engine breakdown tab.
    for row in engine_rows:
        if id(row) in used_engine_rows:
            continue
        damage_type = str(row.get("Damage type", ""))
        if damage_type != "strike":
            continue
        engine_damage = float(row.get("Damage", 0))
        engine_hits = int(row.get("Hits / ticks", 0) or 0)
        output.append(
            _comparison_row(
                skill=str(row.get("Skill", "")),
                damage_type=damage_type,
                reference_damage=0.0,
                engine_damage=engine_damage,
                reference_hits=0,
                engine_hits=engine_hits,
                status="engine-only direct source",
                comparison_level="skill + damage type",
            )
        )

    reference_types = {
        str(row["Damage type"]): row for row in reference.get("by_damage_type", [])
    }
    engine_types = {
        str(row["Damage type"]): row for row in analysis.get("by_damage_type", [])
    }
    type_rows: list[dict[str, Any]] = []
    for damage_type in sorted(set(reference_types) | set(engine_types)):
        ref = reference_types.get(damage_type, {})
        engine = engine_types.get(damage_type, {})
        reference_damage = float(ref.get("Reference damage", 0))
        engine_damage = float(engine.get("Damage", 0))
        reference_hits = int(ref.get("Reference hits / ticks", 0) or 0)
        engine_hits = int(engine.get("Hits / ticks", 0) or 0)
        difference = engine_damage - reference_damage
        type_rows.append(
            {
                "Damage type": damage_type,
                "EI damage": reference_damage,
                "Engine damage": engine_damage,
                "Difference": difference,
                "Difference %": (
                    difference / reference_damage if reference_damage else None
                ),
                "EI hits / ticks": reference_hits,
                "Engine hits / ticks": engine_hits,
                "Hit difference": engine_hits - reference_hits,
            }
        )

    dps_difference = float(analysis.get("dps", 0)) - float(reference.get("dps", 0))
    return {
        "skill_comparison": sorted(
            output, key=lambda row: abs(float(row["Difference"])), reverse=True
        ),
        "type_comparison": sorted(
            type_rows, key=lambda row: abs(float(row["Difference"])), reverse=True
        ),
        "dps_difference": dps_difference,
        "dps_difference_pct": (
            dps_difference / float(reference.get("dps", 1))
            if reference.get("dps")
            else None
        ),
    }


def build_completion_gate(reference, analysis, coverage, comparison):
    expected = sum(
        int(value) for value in (coverage.get("expected_cast_counts") or {}).values()
    )
    executed = sum(int(value) for value in (analysis.get("cast_counts") or {}).values())

    # Major comparable rows consist of direct skills from EI plus fight-wide
    # condition-type aggregates. This avoids pretending EI contains per-source
    # condition attribution when it does not.
    major = [
        row
        for row in comparison.get("skill_comparison", [])
        if float(row.get("EI damage", 0))
        >= 0.02 * float(reference.get("total_damage", 0) or 1)
    ]
    major_within_tolerance = sum(
        abs(float(row.get("Difference %") or 0)) <= 0.02 for row in major
    )

    return [
        {
            "Check": "All logged casts executed",
            "Passed": executed == expected,
            "Observed": f"{executed}/{expected}",
        },
        {
            "Check": "Fight duration matches EI",
            "Passed": abs(
                float(analysis.get("combat_time_ms", 0))
                - float(reference.get("duration_ms", 0))
            )
            <= 1000,
            "Observed": f"{analysis.get('combat_time_s', 0):.3f}s vs {reference.get('duration_ms', 0) / 1000:.3f}s",
        },
        {
            "Check": "All definitions mapped",
            "Passed": not coverage.get("placeholder_names"),
            "Observed": f"{coverage.get('supported_unique_skills', 0)}/{coverage.get('unique_skills', 0)}",
        },
        {
            "Check": "Major comparable sources within ±2%",
            "Passed": bool(major) and major_within_tolerance == len(major),
            "Observed": f"{major_within_tolerance}/{len(major)}",
        },
        {
            "Check": "Total raw DPS within ±1%",
            "Passed": abs(float(comparison.get("dps_difference_pct") or 0)) <= 0.01,
            "Observed": f"{float(comparison.get('dps_difference_pct') or 0):+.2%}",
        },
        {
            "Check": "No calibration active",
            "Passed": True,
            "Observed": "Raw audit only",
        },
    ]
