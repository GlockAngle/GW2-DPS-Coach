from __future__ import annotations

from typing import Any

from utils.parser import (
    fetch_report_json,
    normalize_dps_report_url,
)


# --------------------------------------------------
# Configuration
# --------------------------------------------------

# This matches the uploaded spreadsheet code:
# 0.02 = 2% strike-damage bonus per condition.
EXPOSED_WEAKNESS_PER_CONDITION = 0.02


GW2_TARGET_CONDITIONS = [
    {"id": 736, "name": "Bleeding"},
    {"id": 720, "name": "Blind"},
    {"id": 737, "name": "Burning"},
    {"id": 722, "name": "Chilled"},
    {"id": 861, "name": "Confusion"},
    {"id": 721, "name": "Crippled"},
    {"id": 791, "name": "Fear"},
    {"id": 727, "name": "Immobilized"},
    {"id": 723, "name": "Poisoned"},
    {"id": 26766, "name": "Slow"},
    {"id": 27705, "name": "Taunt"},
    {"id": 19426, "name": "Torment"},
    {"id": 738, "name": "Vulnerability"},
    {"id": 742, "name": "Weakness"},
]


CONDITION_NAMES = [
    condition["name"]
    for condition in GW2_TARGET_CONDITIONS
]


# --------------------------------------------------
# Generic number helpers
# --------------------------------------------------

def as_float(
    value: Any,
    default: float = 0.0,
) -> float:
    """Safely convert a value into a float."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return default

    return number


# --------------------------------------------------
# Fight duration
# --------------------------------------------------

def get_condition_fight_duration_ms(
    report: dict[str, Any],
) -> float:
    """
    Return fight duration in milliseconds.

    The spreadsheet primarily uses durationMS.
    """

    duration_ms = as_float(
        report.get("durationMS"),
        default=0.0,
    )

    if duration_ms > 0:
        return duration_ms

    # Safe fallback for reports containing seconds instead.
    duration = report.get("duration")

    if isinstance(duration, (int, float)):
        numeric_duration = float(duration)

        if numeric_duration > 1000:
            return numeric_duration

        if numeric_duration > 0:
            return numeric_duration * 1000

    raise ValueError(
        "No valid durationMS was found in this report."
    )


# --------------------------------------------------
# Timeline normalization
# --------------------------------------------------

def normalize_state_timeline(
    raw_states: Any,
    duration_ms: float,
) -> list[list[float]]:
    """
    Normalize an Elite Insights state timeline.

    Each state is expected to look like:

        [timestamp_ms, value]

    The final result:
    - is sorted by time;
    - removes invalid states;
    - resolves duplicate timestamps;
    - starts at zero;
    - excludes states after the fight.
    """

    if not isinstance(raw_states, list):
        return []

    cleaned: list[list[float]] = []

    for state in raw_states:
        if not isinstance(state, list):
            continue

        if len(state) < 2:
            continue

        try:
            timestamp = float(state[0])
            value = max(0.0, float(state[1]))
        except (TypeError, ValueError):
            continue

        cleaned.append(
            [timestamp, value]
        )

    if not cleaned:
        return []

    cleaned.sort(
        key=lambda state: state[0]
    )

    deduplicated: list[list[float]] = []

    for timestamp, value in cleaned:
        if (
            deduplicated
            and deduplicated[-1][0] == timestamp
        ):
            # Last state at the same timestamp wins.
            deduplicated[-1][1] = value
        else:
            deduplicated.append(
                [timestamp, value]
            )

    value_at_zero = 0.0

    for timestamp, value in deduplicated:
        if timestamp <= 0:
            value_at_zero = value

    result: list[list[float]] = [
        [0.0, value_at_zero]
    ]

    for timestamp, value in deduplicated:
        if 0 < timestamp < duration_ms:
            if result[-1][0] == timestamp:
                result[-1][1] = value
            else:
                result.append(
                    [timestamp, value]
                )

    return result


# --------------------------------------------------
# Timeline calculations
# --------------------------------------------------

def calculate_timeline_active_duration(
    raw_states: Any,
    duration_ms: float,
) -> float:
    """
    Calculate how long a condition had at least one stack.
    """

    states = normalize_state_timeline(
        raw_states,
        duration_ms,
    )

    if not states:
        return 0.0

    active_duration = 0.0

    for index, state in enumerate(states):
        current_time = state[0]
        current_value = state[1]

        if index + 1 < len(states):
            next_time = states[index + 1][0]
        else:
            next_time = duration_ms

        interval_start = max(
            0.0,
            current_time,
        )

        interval_end = min(
            duration_ms,
            next_time,
        )

        if (
            current_value > 0
            and interval_end > interval_start
        ):
            active_duration += (
                interval_end - interval_start
            )

    return active_duration


def calculate_average_state_value(
    timeline: list[list[float]],
    duration_ms: float,
) -> float:
    """
    Calculate the time-weighted average value of a timeline.
    """

    if not timeline or duration_ms <= 0:
        return 0.0

    weighted_total = 0.0

    for index, state in enumerate(timeline):
        current_time = state[0]
        current_value = state[1]

        if index + 1 < len(timeline):
            next_time = timeline[index + 1][0]
        else:
            next_time = duration_ms

        interval_start = max(
            0.0,
            current_time,
        )

        interval_end = min(
            duration_ms,
            next_time,
        )

        if interval_end > interval_start:
            weighted_total += (
                current_value
                * (interval_end - interval_start)
            )

    return weighted_total / duration_ms


def calculate_timeline_average_in_interval(
    timeline: list[list[float]],
    interval_start_ms: float,
    interval_end_ms: float,
) -> float:
    """
    Calculate the average timeline value inside one interval.
    """

    if (
        not timeline
        or interval_end_ms <= interval_start_ms
    ):
        return 0.0

    weighted_value = 0.0

    interval_duration = (
        interval_end_ms - interval_start_ms
    )

    for index, state in enumerate(timeline):
        state_start = state[0]
        state_value = state[1]

        if index + 1 < len(timeline):
            state_end = timeline[index + 1][0]
        else:
            state_end = interval_end_ms

        overlap_start = max(
            interval_start_ms,
            state_start,
        )

        overlap_end = min(
            interval_end_ms,
            state_end,
        )

        if overlap_end > overlap_start:
            weighted_value += (
                state_value
                * (overlap_end - overlap_start)
            )

        if state_start >= interval_end_ms:
            break

    return weighted_value / interval_duration


# --------------------------------------------------
# Target selection
# --------------------------------------------------

def find_main_target_index(
    targets: list[dict[str, Any]],
) -> int:
    """
    Select the main target.

    The spreadsheet chooses the target with the
    highest total health when multiple targets exist.
    """

    if not targets:
        raise ValueError(
            "No targets were found in the report."
        )

    if len(targets) == 1:
        return 0

    best_index = 0
    best_health = -1.0

    for index, target in enumerate(targets):
        total_health = as_float(
            target.get("totalHealth"),
            default=0.0,
        )

        if total_health > best_health:
            best_health = total_health
            best_index = index

    return best_index


# --------------------------------------------------
# Player selection and strike damage
# --------------------------------------------------

def get_player_target_power_timeline(
    player: dict[str, Any],
    target_index: int,
) -> list[float]:
    """
    Read the cumulative target strike-damage timeline.

    Preferred EI structure:

        targetPowerDamage1S[target][phase]

    Phase zero is the full fight.
    """

    target_power_damage = player.get(
        "targetPowerDamage1S"
    )

    if (
        isinstance(target_power_damage, list)
        and target_index < len(target_power_damage)
        and isinstance(
            target_power_damage[target_index],
            list,
        )
        and target_power_damage[target_index]
        and isinstance(
            target_power_damage[target_index][0],
            list,
        )
    ):
        return [
            as_float(value)
            for value in
            target_power_damage[target_index][0]
        ]

    # Spreadsheet fallback for a single target.
    power_damage = player.get(
        "powerDamage1S"
    )

    if (
        target_index == 0
        and isinstance(power_damage, list)
        and power_damage
        and isinstance(power_damage[0], list)
    ):
        return [
            as_float(value)
            for value in power_damage[0]
        ]

    return []


def find_main_player(
    players: list[dict[str, Any]],
    target_index: int,
) -> dict[str, Any]:
    """
    Select the player with the highest damage
    against the selected target.
    """

    best_result: dict[str, Any] | None = None

    for player in players:
        if not isinstance(player, dict):
            continue

        dps_targets = player.get(
            "dpsTargets"
        )

        if not isinstance(dps_targets, list):
            continue

        if target_index >= len(dps_targets):
            continue

        target_entries = dps_targets[
            target_index
        ]

        if (
            not isinstance(target_entries, list)
            or not target_entries
            or not isinstance(
                target_entries[0],
                dict,
            )
        ):
            continue

        target_dps = target_entries[0]

        total_damage = as_float(
            target_dps.get("damage"),
            default=0.0,
        )

        strike_damage = as_float(
            target_dps.get("powerDamage"),
            default=0.0,
        )

        power_damage_timeline = (
            get_player_target_power_timeline(
                player,
                target_index,
            )
        )

        if (
            best_result is None
            or total_damage
            > best_result["total_damage"]
        ):
            best_result = {
                "player_name": (
                    player.get("name")
                    or player.get("account")
                    or "Unknown player"
                ),
                "profession": (
                    player.get("eliteSpec")
                    or player.get("profession")
                    or ""
                ),
                "total_damage": total_damage,
                "strike_damage": strike_damage,
                "power_damage_timeline": (
                    power_damage_timeline
                ),
            }

    if best_result is None:
        raise ValueError(
            "No player damage against the main "
            "target was found."
        )

    return best_result


# --------------------------------------------------
# Individual condition uptimes
# --------------------------------------------------

def calculate_individual_condition_uptimes(
    target: dict[str, Any],
    duration_ms: float,
) -> dict[str, float]:
    """
    Calculate the uptime percentage of every condition.

    One or more stacks count as present.
    Additional stacks do not increase the condition count.
    """

    result = {
        condition["name"]: 0.0
        for condition in GW2_TARGET_CONDITIONS
    }

    target_buffs = target.get("buffs")

    if not isinstance(target_buffs, list):
        return result

    conditions_by_id = {
        int(condition["id"]): condition["name"]
        for condition in GW2_TARGET_CONDITIONS
    }

    for buff in target_buffs:
        if not isinstance(buff, dict):
            continue

        try:
            buff_id = int(buff.get("id"))
        except (TypeError, ValueError):
            continue

        condition_name = conditions_by_id.get(
            buff_id
        )

        if not condition_name:
            continue

        states = buff.get("states")

        active_duration_ms = (
            calculate_timeline_active_duration(
                states,
                duration_ms,
            )
        )

        if duration_ms > 0:
            result[condition_name] = (
                active_duration_ms
                / duration_ms
                * 100
            )

    return result


# --------------------------------------------------
# Damage-weighted condition calculation
# --------------------------------------------------

def calculate_damage_weighted_conditions(
    cumulative_power_damage: list[float],
    condition_timeline: list[list[float]],
    duration_ms: float,
) -> dict[str, float]:
    """
    Calculate condition count weighted by strike damage.

    The power-damage array is cumulative. Damage in
    each second is calculated by subtracting the
    preceding cumulative value.
    """

    if len(cumulative_power_damage) < 2:
        return {
            "average_conditions": 0.0,
            "total_weighted_damage": 0.0,
            "estimated_trait_damage": 0.0,
        }

    total_damage = 0.0
    weighted_condition_damage = 0.0
    estimated_trait_damage = 0.0

    for second_index in range(
        1,
        len(cumulative_power_damage),
    ):
        previous_cumulative = as_float(
            cumulative_power_damage[
                second_index - 1
            ],
            default=0.0,
        )

        current_cumulative = as_float(
            cumulative_power_damage[
                second_index
            ],
            default=0.0,
        )

        damage_this_second = max(
            0.0,
            current_cumulative
            - previous_cumulative,
        )

        if damage_this_second <= 0:
            continue

        interval_start_ms = (
            second_index - 1
        ) * 1000

        interval_end_ms = min(
            second_index * 1000,
            duration_ms,
        )

        if (
            interval_end_ms
            <= interval_start_ms
        ):
            continue

        average_conditions_this_second = (
            calculate_timeline_average_in_interval(
                condition_timeline,
                interval_start_ms,
                interval_end_ms,
            )
        )

        bonus_fraction = (
            average_conditions_this_second
            * EXPOSED_WEAKNESS_PER_CONDITION
        )

        # Logged strike damage already includes EW.
        if bonus_fraction > 0:
            trait_part_this_second = (
                damage_this_second
                * (
                    bonus_fraction
                    / (1 + bonus_fraction)
                )
            )
        else:
            trait_part_this_second = 0.0

        total_damage += damage_this_second

        weighted_condition_damage += (
            damage_this_second
            * average_conditions_this_second
        )

        estimated_trait_damage += (
            trait_part_this_second
        )

    if total_damage > 0:
        average_conditions = (
            weighted_condition_damage
            / total_damage
        )
    else:
        average_conditions = 0.0

    return {
        "average_conditions": average_conditions,
        "total_weighted_damage": total_damage,
        "estimated_trait_damage": (
            estimated_trait_damage
        ),
    }


# --------------------------------------------------
# Complete analysis
# --------------------------------------------------

def analyse_conditions(
    report: dict[str, Any],
) -> dict[str, Any]:
    """
    Run the spreadsheet-compatible conditions and
    Exposed Weakness analysis for one report.

    The corrected EW result uses:
    - 10 intended permanent conditions
    - plus the actual Taunt uptime
    """

    if not isinstance(report, dict):
        raise ValueError(
            "The supplied report is not valid JSON."
        )

    targets = report.get("targets")
    players = report.get("players")

    if not isinstance(targets, list) or not targets:
        raise ValueError(
            "No targets were found in the report."
        )

    if not isinstance(players, list) or not players:
        raise ValueError(
            "No players were found in the report."
        )

    duration_ms = get_condition_fight_duration_ms(
        report
    )

    duration_seconds = duration_ms / 1000

    target_index = find_main_target_index(
        targets
    )

    target = targets[target_index]

    if not isinstance(target, dict):
        raise ValueError(
            "The selected target is invalid."
        )

    player_result = find_main_player(
        players,
        target_index,
    )

    condition_uptimes = (
        calculate_individual_condition_uptimes(
            target,
            duration_ms,
        )
    )

    target_condition_timeline = (
        normalize_state_timeline(
            target.get(
                "conditionsStates",
                [],
            ),
            duration_ms,
        )
    )

    average_unique_conditions = (
        calculate_average_state_value(
            target_condition_timeline,
            duration_ms,
        )
    )

    uptime_sum_conditions = sum(
        condition_uptimes.get(
            condition_name,
            0.0,
        )
        / 100
        for condition_name in CONDITION_NAMES
    )

    condition_check_difference = (
        average_unique_conditions
        - uptime_sum_conditions
    )

    strike_damage = float(
        player_result["strike_damage"]
    )

    if duration_seconds > 0:
        strike_dps = (
            strike_damage
            / duration_seconds
        )
    else:
        strike_dps = 0.0

    damage_weighted_result = (
        calculate_damage_weighted_conditions(
            player_result[
                "power_damage_timeline"
            ],
            target_condition_timeline,
            duration_ms,
        )
    )

    simple_bonus_fraction = (
        average_unique_conditions
        * EXPOSED_WEAKNESS_PER_CONDITION
    )

    damage_weighted_conditions = (
        damage_weighted_result[
            "average_conditions"
        ]
    )

    weighted_bonus_fraction = (
        damage_weighted_conditions
        * EXPOSED_WEAKNESS_PER_CONDITION
    )

    estimated_trait_damage = (
        damage_weighted_result[
            "estimated_trait_damage"
        ]
    )

    estimated_damage_without_trait = max(
        0.0,
        strike_damage
        - estimated_trait_damage,
    )

    if duration_seconds > 0:
        estimated_trait_dps = (
            estimated_trait_damage
            / duration_seconds
        )
    else:
        estimated_trait_dps = 0.0

    # --------------------------------------------------
    # Spreadsheet correction:
    # intended setup = 10 conditions + Taunt uptime
    # --------------------------------------------------

    base_conditions = 10.0

    taunt_uptime_percent = (
        condition_uptimes.get(
            "Taunt",
            0.0,
        )
    )

    taunt_uptime_fraction = (
        taunt_uptime_percent
        / 100
    )

    intended_conditions = (
        base_conditions
        + taunt_uptime_fraction
    )

    excess_conditions = max(
        0.0,
        average_unique_conditions
        - intended_conditions,
    )

    if average_unique_conditions > 0:
        incorrect_ew_share = (
            excess_conditions
            / average_unique_conditions
        )
    else:
        incorrect_ew_share = 0.0

    correction_dps = (
        estimated_trait_dps
        * incorrect_ew_share
    )

    corrected_ew_dps = max(
        0.0,
        estimated_trait_dps
        - correction_dps,
    )

    return {
        "fight_name": (
            report.get("fightName")
            or report.get("name")
            or ""
        ),
        "success": report.get("success"),
        "duration_seconds": duration_seconds,

        "player_name": player_result[
            "player_name"
        ],
        "profession": player_result[
            "profession"
        ],

        "target_name": (
            target.get("name")
            or f"Target {target_index + 1}"
        ),

        "condition_uptimes": (
            condition_uptimes
        ),

        "average_unique_conditions": (
            average_unique_conditions
        ),

        "uptime_sum_conditions": (
            uptime_sum_conditions
        ),

        "condition_check_difference": (
            condition_check_difference
        ),

        "simple_bonus_percent": (
            simple_bonus_fraction
            * 100
        ),

        "damage_weighted_conditions": (
            damage_weighted_conditions
        ),

        "damage_weighted_bonus_percent": (
            weighted_bonus_fraction
            * 100
        ),

        "strike_damage": (
            strike_damage
        ),

        "strike_dps": (
            strike_dps
        ),

        "estimated_damage_without_trait": (
            estimated_damage_without_trait
        ),

        "estimated_trait_damage": (
            estimated_trait_damage
        ),

        "estimated_trait_dps": (
            estimated_trait_dps
        ),

        # Corrected 10 conditions + Taunt values
        "base_conditions": (
            base_conditions
        ),

        "taunt_uptime_percent": (
            taunt_uptime_percent
        ),

        "taunt_uptime_fraction": (
            taunt_uptime_fraction
        ),

        "intended_conditions": (
            intended_conditions
        ),

        "excess_conditions": (
            excess_conditions
        ),

        "incorrect_ew_share": (
            incorrect_ew_share
        ),

        "incorrect_ew_share_percent": (
            incorrect_ew_share
            * 100
        ),

        "correction_dps": (
            correction_dps
        ),

        "corrected_ew_dps": (
            corrected_ew_dps
        ),

        "total_damage": player_result[
            "total_damage"
        ],

        "status": "OK",
    }

def analyse_conditions_from_url(
    report_url: str,
) -> dict[str, Any]:
    """
    Download and analyse one dps.report link.
    """

    report = fetch_report_json(
        report_url
    )

    result = analyse_conditions(
        report
    )

    result["report_url"] = (
        normalize_dps_report_url(
            report_url
        )
    )

    return result