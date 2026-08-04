"""Timeline-conditioned benchmark prediction using Combat Engine v1.

This module never reads observed damage values to calculate predicted damage.
It may use the observed cast/hit timeline because the purpose of this pass is to
answer: "what damage should this exact action sequence produce?"
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .combat_engine_v1 import CharacterSnapshot, ConditionEvent, StrikeEvent, simulate_condition_event, simulate_strike_event
from .damage_engine import DamageModifiers, ModifierSource, get_weapon_strength

ROOT = Path(__file__).resolve().parents[1]
CORE_STATS = ("Power", "Toughness", "Vitality", "Precision", "Ferocity", "Condition Damage", "Expertise", "Concentration", "Defense", "Healing Power")
BASE_STATS = {"Power": 1000.0, "Toughness": 1000.0, "Vitality": 1000.0, "Precision": 1000.0, "Ferocity": 0.0, "Condition Damage": 0.0, "Expertise": 0.0, "Concentration": 0.0, "Defense": 0.0, "Healing Power": 0.0}


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _add_stats(target: dict[str, float], source: dict[str, Any], factor: float = 1.0) -> None:
    for stat in CORE_STATS:
        target[stat] += _number(source.get(stat)) * factor


def build_saved_benchmark_profile() -> dict[str, Any]:
    """Build the bundled Condi Antiquary stat snapshot without Streamlit state."""
    gear_data = json.loads((ROOT / "data" / "gear_data.json").read_text(encoding="utf-8"))
    saved = json.loads((ROOT / "data" / "saved_builds.json").read_text(encoding="utf-8"))["Condi Antiquary"]
    stats = dict(BASE_STATS)
    sources: dict[str, dict[str, float]] = {}

    equipment = {stat: 0.0 for stat in CORE_STATS}
    for slot, prefix in saved["gear"].items():
        table = gear_data["prefix_tables"][gear_data["slots"][slot]]
        _add_stats(equipment, table.get(prefix, {}))
    _add_stats(stats, equipment)
    sources["Equipment"] = equipment

    food = gear_data["food"].get(saved["food"], {})
    _add_stats(stats, food)
    sources["Food"] = {stat: _number(food.get(stat)) for stat in CORE_STATS}

    inf = gear_data["infusions"].get(saved["infusion"], {})
    inf_stats = {stat: _number(inf.get(stat)) * int(saved["infusion_count"]) for stat in CORE_STATS}
    _add_stats(stats, inf_stats)
    sources["Infusions"] = inf_stats

    rune = gear_data["runes"].get(saved["rune"], {})
    rune_stats = {stat: _number(rune.get(stat)) for stat in CORE_STATS}
    _add_stats(stats, rune_stats)
    sources["Rune"] = rune_stats

    sigil_stats = {stat: 0.0 for stat in CORE_STATS}
    for sigil_name in (saved["sigil_1"], saved["sigil_2"]):
        _add_stats(sigil_stats, gear_data["sigils"].get(sigil_name, {}))
    _add_stats(stats, sigil_stats)
    sources["Sigils"] = sigil_stats

    # Utility formulas in the bundled data are evaluated after direct gear sources.
    utility_name = saved["utility"]
    utility = gear_data["utility"].get(utility_name, {})
    utility_stats = {stat: _number(utility.get(stat)) for stat in CORE_STATS}
    if utility_name == "Toxic Focusing Crystal":
        utility_stats["Condition Damage"] = stats["Power"] * 0.03 + stats["Precision"] * 0.03
    _add_stats(stats, utility_stats)
    sources["Utility"] = utility_stats

    might = max(0, min(25, int(saved.get("might_stacks", 0)))) * 30.0
    stats["Power"] += might
    stats["Condition Damage"] += might
    sources["Might"] = {**{stat: 0.0 for stat in CORE_STATS}, "Power": might, "Condition Damage": might}

    generic_duration = min(1.0, stats["Expertise"] / 1500.0 + _number(rune.get("Condition Duration")))
    specific = {name: generic_duration for name in ("Bleeding", "Burning", "Confusion", "Poison", "Torment")}
    specific["Bleeding"] = min(1.0, generic_duration + _number(food.get("Bleeding Duration")) + sum(_number(gear_data["sigils"].get(s, {}).get("Bleeding Duration")) for s in (saved["sigil_1"], saved["sigil_2"])))

    # Benchmark traits: Deadly Ambition provides +180 condition damage in PvE.
    # Its poison-on-dual-wield packet is generated in the timeline pass below.
    stats["Condition Damage"] += 180.0
    sources["Deadly Ambition"] = {**{stat: 0.0 for stat in CORE_STATS}, "Condition Damage": 180.0}

    # Confirmed from the selected benchmark build discussion.
    specific["Poison"] = min(1.0, specific["Poison"] + 0.33)
    modifiers = DamageModifiers(
        condition_specific_sources={
            "Poison": (ModifierSource("Potent Poison (PvE)", 0.33),),
        }
    )
    crit_chance = min(1.0, max(0.0, 0.05 + (stats["Precision"] - 1000.0) / 2100.0 + 0.25))
    crit_damage = 1.5 + stats["Ferocity"] / 1500.0
    snapshot = CharacterSnapshot(
        power=stats["Power"], condition_damage=stats["Condition Damage"],
        precision=stats["Precision"], ferocity=stats["Ferocity"],
        weapon_strength=get_weapon_strength("Dagger", saved.get("weapon_strength_mode", "Midpoint")),
        enemy_armor=float(saved.get("enemy_armor", 2597)),
        vulnerability_stacks=int(saved.get("enemy_vulnerability", 25)),
        critical_chance=crit_chance, critical_damage=crit_damage, modifiers=modifiers,
    )
    return {
        "snapshot": snapshot,
        "stats": stats,
        "sources": sources,
        "condition_duration_bonus": specific,
        "build": saved,
        "confirmed_modifiers": [
            "Potent Poison: +33% Poison damage and duration",
            "Deadly Ambition: +180 Condition Damage and 2 Poison stacks for 3s per dual-wield use with Potent Poison",
            "Lead Attacks and Combat High: timeline stack states from Elite Insights",
            "Exposed Weakness, Twin Fangs, Ferocious Strikes, Executioner: benchmark trait rules",
            "Superior Sigil of Earth: 1 Bleeding for 6s, 2s ICD",
            "Relic of the Fractal: 2 Burning + 3 Torment for 8s, 20s ICD",
        ],
        "unresolved_modifiers": [
            "Artifact child strike coefficients without explicit skill records remain unsupported",
            "Exact per-hit timestamps are unavailable; Earth Sigil and strike modifiers use cast-time reconstruction",
        ],
    }


def _skill_name(report: dict[str, Any], sid: int) -> str:
    return report.get("skillMap", {}).get(f"s{sid}", {}).get("name", f"Skill {sid}")


def _casts_by_skill(report: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    return {int(row["id"]): list(row.get("skills", [])) for row in report["players"][0].get("rotation", [])}


def _observed_hits(report: dict[str, Any]) -> dict[int, int]:
    rows = report["players"][0].get("targetDamageDist", [[[]]])[0][0]
    return {int(row.get("id", 0)): int(row.get("connectedHits", 0) or 0) for row in rows}



def _buff_states(report: dict[str, Any], buff_id: int) -> list[tuple[float, float]]:
    for row in report.get("players", [{}])[0].get("buffUptimes", []):
        if int(row.get("id", 0)) == buff_id:
            return [(float(t) / 1000.0, float(v)) for t, v in row.get("states", [])]
    return []

def _state_at(states: list[tuple[float, float]], at_s: float, default: float = 0.0) -> float:
    value = default
    for t, v in states:
        if t > at_s:
            break
        value = v
    return value

def _trait_multiplier(report: dict[str, Any], at_s: float, *, strike: bool) -> float:
    # These are selected benchmark traits/effects. Dynamic stacks are read from
    # EI state timelines, never from observed damage values.
    lead = _state_at(_buff_states(report, 34659), at_s)
    combat_high = _state_at(_buff_states(report, 76785), at_s)
    mult = (1.0 + 0.01 * lead)
    mult *= (1.0 + (0.03 if strike else 0.02) * combat_high)
    if strike:
        mult *= 1.10  # Exposed Weakness: five benchmark conditions x 2%
        health_fraction = max(0.0, 1.0 - at_s / max(0.001, float(report.get("durationMS", 1)) / 1000.0))
        if health_fraction >= 0.5:
            mult *= 1.07  # Twin Fangs
            # Ferocious Strikes affects only critical strike portion. Convert to
            # an expected-value multiplier using the frozen critical chance.
            mult *= 1.0 + 0.10 * 0.6014285714285714
        else:
            mult *= 1.20  # Executioner
        if _state_at(_buff_states(report, 77931), at_s) > 0:
            mult *= 1.15  # Kryptis Turret unique passive
    return mult

def _add_condition_packet(snapshot: CharacterSnapshot, durations: dict[str, float], fight_s: float, at_s: float, name: str, condition: str, stacks: float, base_duration: float) -> float:
    effective = min(base_duration * (1.0 + durations[condition]), max(0.0, fight_s - at_s))
    if effective <= 0:
        return 0.0
    result = simulate_condition_event(snapshot, ConditionEvent(name, condition, stacks, effective, 1))
    return float(result["expected_total_damage"])

def build_full_benchmark_prediction(report: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Predict supported events across the exact uploaded benchmark timeline."""
    profile = build_saved_benchmark_profile()
    snapshot: CharacterSnapshot = profile["snapshot"]
    durations: dict[str, float] = profile["condition_duration_bonus"]
    fight_s = float(report.get("durationMS", 0) or 0) / 1000.0
    casts = _casts_by_skill(report)
    observed_hits = _observed_hits(report)

    source_totals: dict[int, dict[str, Any]] = {}
    unsupported: list[dict[str, Any]] = []
    total_strike = 0.0
    total_condition = 0.0
    predicted_events = 0

    for sid, cast_rows in casts.items():
        override = overrides.get(str(sid), {})
        name = _skill_name(report, sid)
        source = source_totals.setdefault(sid, {"skill_id": sid, "name": name, "casts": len(cast_rows), "predicted_strike": 0.0, "predicted_condition": 0.0, "predicted_total": 0.0, "status": "supported"})

        coefficient_total = _number(override.get("power_coefficient"))
        stored_hits = int(_number(override.get("hits")))
        actual_hits = observed_hits.get(sid, 0)
        if coefficient_total > 0 and (stored_hits > 0 or actual_hits > 0):
            # Exact replay uses observed connected hit count where available. The
            # coefficient remains sourced from the verified skill definition.
            hit_count = actual_hits if actual_hits > 0 else stored_hits * len(cast_rows)
            coefficient_per_hit = coefficient_total / max(1, stored_hits)
            # Reconstruct hits across casts so time-dependent traits are applied.
            base_per_hit = simulate_strike_event(snapshot, StrikeEvent(name, coefficient_per_hit, 1))["expected_total_damage"]
            per_cast_hits = hit_count / max(1, len(cast_rows))
            strike_damage = 0.0
            for cast in cast_rows:
                at_s = _number(cast.get("castTime")) / 1000.0
                strike_damage += base_per_hit * per_cast_hits * _trait_multiplier(report, at_s, strike=True)
            source["predicted_strike"] += strike_damage
            total_strike += strike_damage
            predicted_events += hit_count
        elif actual_hits > 0:
            source["status"] = "partial"
            unsupported.append({"skill_id": sid, "name": name, "kind": "strike", "reason": f"{actual_hits} observed hits but no verified coefficient"})

        events = override.get("condition_events") or []
        for cast in cast_rows:
            cast_s = _number(cast.get("castTime")) / 1000.0
            for event in events:
                condition = str(event.get("condition", ""))
                if condition not in durations:
                    continue
                repeats = int(_number(event.get("hits", event.get("charges", 1))) or 1)
                interval = _number(event.get("interval"))
                stacks = _number(event.get("stacks_per_application", event.get("stacks", 1))) or 1.0
                applications = int(_number(event.get("applications_per_hit", event.get("applications_per_trigger", 1))) or 1)
                base_duration = _number(event.get("base_duration", event.get("duration", 0)))
                modified_duration = base_duration * (1.0 + durations[condition])
                for repeat in range(repeats):
                    application_time = cast_s + repeat * interval
                    remaining = max(0.0, fight_s - application_time)
                    effective_duration = min(modified_duration, remaining)
                    if effective_duration <= 0:
                        continue
                    result = simulate_condition_event(snapshot, ConditionEvent(f"{name}: {event.get('phase', 'condition')}", condition, stacks, effective_duration, applications))
                    damage = result["expected_total_damage"] * _trait_multiplier(report, application_time, strike=False)
                    source["predicted_condition"] += damage
                    total_condition += damage
                    predicted_events += applications

        if not coefficient_total and not events and len(cast_rows):
            source["status"] = "unsupported"
            unsupported.append({"skill_id": sid, "name": name, "kind": "skill", "reason": "No independent strike coefficient or condition packet"})

    # Trait/relic/sigil packets that are not ordinary cast rows.
    proc_rows: list[dict[str, Any]] = []

    # Deadly Ambition: Death Blossom is a dual-wield attack. Potent Poison makes
    # this other Deadly Arts trait apply one additional poison stack.
    da_damage = 0.0
    for cast in casts.get(13006, []):
        at_s = _number(cast.get("castTime")) / 1000.0
        da_damage += _add_condition_packet(snapshot, durations, fight_s, at_s, "Deadly Ambition", "Poison", 2, 3.0) * _trait_multiplier(report, at_s, strike=False)
    if da_damage:
        total_condition += da_damage
        predicted_events += len(casts.get(13006, []))
        proc_rows.append({"skill_id": -1001, "name": "Deadly Ambition", "casts": len(casts.get(13006, [])), "predicted_strike": 0.0, "predicted_condition": da_damage, "predicted_total": da_damage, "status": "supported"})

    # Superior Sigil of Earth. Without per-hit timestamps, use the earliest cast
    # at or after each 2-second ICD while attacks are occurring.
    attack_times = sorted(_number(c.get("castTime")) / 1000.0 for rows_ in casts.values() for c in rows_)
    earth_times: list[float] = []
    next_earth = 0.0
    for at_s in attack_times:
        if at_s + 1e-9 >= next_earth:
            earth_times.append(at_s); next_earth = at_s + 2.0
    earth_damage = sum(_add_condition_packet(snapshot, durations, fight_s, t, "Superior Sigil of Earth", "Bleeding", 1, 6.0) * _trait_multiplier(report, t, strike=False) for t in earth_times)
    if earth_damage:
        total_condition += earth_damage; predicted_events += len(earth_times)
        proc_rows.append({"skill_id": -1002, "name": "Superior Sigil of Earth", "casts": len(earth_times), "predicted_strike": 0.0, "predicted_condition": earth_damage, "predicted_total": earth_damage, "status": "supported"})

    # Relic of the Fractal, benchmark PvE packet and 20-second ICD. Trigger from
    # the first available bleeding application after each ICD once ramped.
    bleed_times = sorted(_number(c.get("castTime")) / 1000.0 for sid in (13006, 13087, 13028, 56898) for c in casts.get(sid, []))
    relic_times: list[float] = []
    next_relic = 0.0
    for at_s in bleed_times:
        if at_s >= 1.0 and at_s + 1e-9 >= next_relic:
            relic_times.append(at_s); next_relic = at_s + 20.0
    relic_damage = 0.0
    for t in relic_times:
        relic_damage += _add_condition_packet(snapshot, durations, fight_s, t, "Relic of the Fractal", "Burning", 2, 8.0) * _trait_multiplier(report, t, strike=False)
        relic_damage += _add_condition_packet(snapshot, durations, fight_s, t, "Relic of the Fractal", "Torment", 3, 8.0) * _trait_multiplier(report, t, strike=False)
    if relic_damage:
        total_condition += relic_damage; predicted_events += len(relic_times) * 2
        proc_rows.append({"skill_id": -1003, "name": "Relic of the Fractal", "casts": len(relic_times), "predicted_strike": 0.0, "predicted_condition": relic_damage, "predicted_total": relic_damage, "status": "supported"})

    # Damage child rows can have no cast row. Keep them explicit rather than hiding them.
    cast_ids = set(casts)
    for sid, hits in observed_hits.items():
        if sid in cast_ids or hits <= 0 or sid in {723, 736, 737, 861, 19426}:
            continue
        override = overrides.get(str(sid), {})
        if not override.get("power_coefficient"):
            unsupported.append({"skill_id": sid, "name": _skill_name(report, sid), "kind": "child_damage", "reason": f"{hits} observed child/proc hits without a standalone verified coefficient"})

    rows = []
    for source in list(source_totals.values()) + proc_rows:
        source["predicted_total"] = source["predicted_strike"] + source["predicted_condition"]
        source["predicted_dps"] = source["predicted_total"] / fight_s if fight_s else 0.0
        for key in ("predicted_strike", "predicted_condition", "predicted_total", "predicted_dps"):
            source[key] = round(source[key], 2)
        rows.append(source)
    rows.sort(key=lambda row: row["predicted_total"], reverse=True)

    predicted_total = total_strike + total_condition
    observed = report["players"][0].get("dpsAll", [{}])[0]
    supported_casts = sum(row["casts"] for row in source_totals.values() if row["status"] != "unsupported")
    total_casts = sum(len(v) for v in casts.values())
    return {
        "summary": {
            "label": "TIMELINE-CONDITIONED PREDICTION v2 — calculated from formulas, not observed damage",
            "fight_duration_s": round(fight_s, 3),
            "observed_ei_dps": int(observed.get("dps", 0) or 0),
            "observed_in_game_dps": 42406,
            "observed_damage": int(observed.get("damage", 0) or 0),
            "predicted_supported_damage": round(predicted_total),
            "predicted_supported_dps": round(predicted_total / fight_s, 2) if fight_s else 0.0,
            "predicted_strike_damage": round(total_strike),
            "predicted_condition_damage": round(total_condition),
            "cast_coverage_pct": round(supported_casts / total_casts * 100, 2) if total_casts else 0.0,
            "unsupported_sources": len(unsupported),
            "full_prediction_ready": len(unsupported) == 0,
            "full_prediction_rule": "This v2 subtotal includes benchmark traits, Earth Sigil, Fractal Relic and timeline stack modifiers. Remaining unsupported child coefficients stay explicit.",
            "event_count": predicted_events,
        },
        "profile": {
            **snapshot.audit_dict(),
            "condition_duration_bonus": {k: round(v, 4) for k, v in durations.items()},
            "confirmed_modifiers": profile["confirmed_modifiers"],
            "unresolved_modifiers": profile["unresolved_modifiers"],
            "stat_sources": profile["sources"],
        },
        "sources": rows,
        "unsupported": unsupported,
    }
