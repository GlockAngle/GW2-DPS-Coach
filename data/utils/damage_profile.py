from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Iterable

from utils.parser import (
    DAMAGE_MULTIPLIER,
    DAMAGE_VALUE_THOUSANDS,
    SPIDER_VENOM_DURATION,
    fetch_report_json,
    get_cast_start_seconds,
    get_killtime,
    get_rotation_casts,
    is_spider_venom_rotation,
    normalize_dps_report_url,
    parse_guild_wars_integer,
)


SPIDER_VENOM_ALLY_DAMAGE_PER_CAST = (
    DAMAGE_MULTIPLIER
    * DAMAGE_VALUE_THOUSANDS
    * 1000
)


@dataclass(frozen=True)
class DamageProfile:
    report_url: str
    player_name: str
    killtime: float
    seconds: list[float]
    solo_dps: list[float]
    corrected_solo_dps: list[float]
    allied_dps: list[float]
    venom_casts: list[float]


def _full_fight_damage(player: dict[str, Any]) -> float:
    """Read full-fight damage from the first dpsAll phase."""
    try:
        return float(player["dpsAll"][0]["damage"])
    except (KeyError, IndexError, TypeError, ValueError):
        pass

    try:
        return float(player["dpsAll"][0][0]["damage"])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0


def _select_main_player(report: dict[str, Any]) -> dict[str, Any]:
    """
    Select the benchmark player.

    Golem logs normally contain one real player. For safety, this
    chooses the non-friendly player with the highest full-fight damage.
    """
    players = [
        player
        for player in report.get("players", [])
        if isinstance(player, dict)
        and not player.get("friendlyNPC", False)
        and not player.get("notInSquad", False)
    ]

    if not players:
        players = [
            player
            for player in report.get("players", [])
            if isinstance(player, dict)
        ]

    if not players:
        raise ValueError("The report contains no player data.")

    return max(players, key=_full_fight_damage)


def _extract_full_fight_cumulative_damage(
    player: dict[str, Any],
) -> list[float]:
    """
    Return the first/full-fight Damage1S phase.

    Elite Insights stores Damage1S as cumulative damage points:
    [0, damage at 1s, damage at 2s, ...].
    """
    damage_1s = player.get("damage1S")

    if not isinstance(damage_1s, list) or not damage_1s:
        raise ValueError(
            "The selected player has no Damage1S timeline."
        )

    # Normal Elite Insights structure: one list per phase.
    if isinstance(damage_1s[0], list):
        phase = damage_1s[0]
    else:
        # Defensive fallback for older/alternate output.
        phase = damage_1s

    cumulative: list[float] = []

    for value in phase:
        try:
            cumulative.append(float(value))
        except (TypeError, ValueError):
            cumulative.append(
                cumulative[-1] if cumulative else 0.0
            )

    if len(cumulative) < 2:
        raise ValueError(
            "The Damage1S timeline does not contain enough points."
        )

    return cumulative


def _cumulative_to_interval_dps(
    cumulative: list[float],
    killtime: float,
) -> tuple[list[float], list[float]]:
    """
    Convert cumulative Damage1S points into interval DPS.

    The final interval may be shorter than one second, so its damage is
    divided by the actual remaining duration.
    """
    interval_dps: list[float] = []
    seconds: list[float] = []

    for index in range(1, len(cumulative)):
        interval_start = float(index - 1)
        interval_end = min(float(index), killtime)
        interval_duration = interval_end - interval_start

        if interval_duration <= 0:
            break

        interval_damage = max(
            0.0,
            cumulative[index] - cumulative[index - 1],
        )

        interval_dps.append(
            interval_damage / interval_duration
        )
        seconds.append(interval_start)

        if interval_end >= killtime:
            break

    if not interval_dps:
        raise ValueError(
            "No per-second damage intervals could be calculated."
        )

    return seconds, interval_dps


def _extract_spider_venom_casts(
    player: dict[str, Any],
) -> list[float]:
    """Extract all Spider Venom cast start times from the player."""
    cast_times: list[float] = []
    rotation = player.get("rotation", [])

    if not isinstance(rotation, list):
        return cast_times

    for rotation_entry in rotation:
        if not isinstance(rotation_entry, dict):
            continue

        if not is_spider_venom_rotation(rotation_entry):
            continue

        for cast in get_rotation_casts(rotation_entry):
            cast_start = get_cast_start_seconds(cast)

            if cast_start is not None:
                cast_times.append(float(cast_start))

    return sorted(cast_times)


def _scale_profile_to_ingame_dps(
    interval_dps: list[float],
    killtime: float,
    ingame_dps: str | int | float | None,
) -> list[float]:
    """
    Scale the raw profile so its fight average matches the entered DPS.

    This preserves the exact damage shape while matching the benchmark
    number shown in game.
    """
    if ingame_dps is None:
        return list(interval_dps)

    target_dps = float(parse_guild_wars_integer(ingame_dps))

    total_damage = 0.0

    for index, value in enumerate(interval_dps):
        interval_duration = min(
            1.0,
            max(0.0, killtime - index),
        )
        total_damage += value * interval_duration

    raw_average = (
        total_damage / killtime
        if killtime > 0
        else 0.0
    )

    if raw_average <= 0:
        return list(interval_dps)

    scale = target_dps / raw_average

    return [
        value * scale
        for value in interval_dps
    ]


def _apply_flat_ew_correction(
    solo_dps: list[float],
    ew_correction_dps: float,
) -> list[float]:
    """
    Subtract EW correction from the solo profile.

    The available benchmark correction is a fight-average DPS value,
    so it is applied evenly across the profile.
    """
    correction = max(0.0, float(ew_correction_dps))

    return [
        max(0.0, value - correction)
        for value in solo_dps
    ]


def _add_spider_venom_to_profile(
    corrected_solo_dps: list[float],
    venom_casts: list[float],
    killtime: float,
) -> list[float]:
    """
    Add allied Spider Venom damage to the relevant timeline intervals.

    Each full cast contributes the same total damage used by parser.py,
    spread evenly across its six-second active window. A final partial
    cast is naturally clipped at killtime.
    """
    allied_dps = list(corrected_solo_dps)
    damage_per_second = (
        SPIDER_VENOM_ALLY_DAMAGE_PER_CAST
        / SPIDER_VENOM_DURATION
    )

    for cast_start in venom_casts:
        active_start = max(0.0, cast_start)
        active_end = min(
            killtime,
            cast_start + SPIDER_VENOM_DURATION,
        )

        if active_end <= active_start:
            continue

        first_interval = max(0, int(active_start))
        last_interval = min(
            len(allied_dps) - 1,
            int(active_end - 1e-9),
        )

        for interval in range(
            first_interval,
            last_interval + 1,
        ):
            interval_start = float(interval)
            interval_end = min(
                interval_start + 1.0,
                killtime,
            )

            overlap = max(
                0.0,
                min(interval_end, active_end)
                - max(interval_start, active_start),
            )

            interval_duration = interval_end - interval_start

            if interval_duration > 0:
                allied_dps[interval] += (
                    damage_per_second
                    * overlap
                    / interval_duration
                )

    return allied_dps


def analyse_damage_profile(
    report_url: str,
    ingame_dps: str | int | float | None = None,
    ew_correction_dps: float = 0.0,
) -> DamageProfile:
    """
    Analyse one dps.report log.

    Parameters
    ----------
    report_url:
        Normal dps.report permalink.
    ingame_dps:
        Optional end number shown in game, such as "41.350".
        When supplied, the raw timeline is scaled to this average.
    ew_correction_dps:
        Fight-average EW correction that must be removed from solo DPS.

    Returns
    -------
    DamageProfile
        Raw solo, EW-corrected solo, corrected allied profile and
        Spider Venom cast timings.
    """
    report = fetch_report_json(report_url)
    player = _select_main_player(report)
    killtime = get_killtime(report)

    cumulative_damage = (
        _extract_full_fight_cumulative_damage(player)
    )
    seconds, raw_solo_dps = (
        _cumulative_to_interval_dps(
            cumulative_damage,
            killtime,
        )
    )

    scaled_solo_dps = _scale_profile_to_ingame_dps(
        raw_solo_dps,
        killtime,
        ingame_dps,
    )

    corrected_solo_dps = _apply_flat_ew_correction(
        scaled_solo_dps,
        ew_correction_dps,
    )

    venom_casts = _extract_spider_venom_casts(player)

    allied_dps = _add_spider_venom_to_profile(
        corrected_solo_dps,
        venom_casts,
        killtime,
    )

    return DamageProfile(
        report_url=normalize_dps_report_url(report_url),
        player_name=str(
            player.get("name", "Unknown player")
        ),
        killtime=killtime,
        seconds=seconds,
        solo_dps=scaled_solo_dps,
        corrected_solo_dps=corrected_solo_dps,
        allied_dps=allied_dps,
        venom_casts=venom_casts,
    )


def _average_profiles(
    profiles: list[DamageProfile],
    field_name: str,
) -> tuple[list[float], list[float]]:
    """
    Average profiles by elapsed second.

    Logs that already ended are excluded from later seconds instead of
    being treated as zero DPS.
    """
    if not profiles:
        return [], []

    longest_profile = max(
        len(getattr(profile, field_name))
        for profile in profiles
    )

    seconds: list[float] = []
    averages: list[float] = []

    for index in range(longest_profile):
        values = [
            float(getattr(profile, field_name)[index])
            for profile in profiles
            if index < len(
                getattr(profile, field_name)
            )
        ]

        if not values:
            continue

        seconds.append(float(index))
        averages.append(sum(values) / len(values))

    return seconds, averages


def build_average_session_profile(
    logs: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """
    Build average profiles for a bulk session.

    Each log dictionary should contain:
    - report_url or Report URL
    - ingame_dps or In-game Damage (optional)
    - ew_correction_dps or EW Correction (optional)
    """
    profiles: list[DamageProfile] = []
    errors: list[str] = []

    for log_number, log in enumerate(logs, start=1):
        report_url = (
            log.get("report_url")
            or log.get("Report URL")
        )
        ingame_dps = (
            log.get("ingame_dps")
            if "ingame_dps" in log
            else log.get("In-game Damage")
        )
        ew_correction = (
            log.get("ew_correction_dps")
            if "ew_correction_dps" in log
            else log.get("EW Correction", 0.0)
        )

        if not report_url:
            errors.append(
                f"Log {log_number}: report URL is missing."
            )
            continue

        try:
            profiles.append(
                analyse_damage_profile(
                    report_url=report_url,
                    ingame_dps=ingame_dps,
                    ew_correction_dps=float(
                        ew_correction or 0.0
                    ),
                )
            )
        except Exception as error:
            errors.append(
                f"Log {log_number}: {error}"
            )

    seconds, average_allied_dps = _average_profiles(
        profiles,
        "allied_dps",
    )
    _, average_corrected_solo_dps = _average_profiles(
        profiles,
        "corrected_solo_dps",
    )

    maximum_cast_count = max(
        (len(profile.venom_casts) for profile in profiles),
        default=0,
    )

    median_venom_casts: list[dict[str, float | int]] = []

    for cast_index in range(maximum_cast_count):
        timings = [
            profile.venom_casts[cast_index]
            for profile in profiles
            if len(profile.venom_casts) > cast_index
        ]

        if timings:
            median_venom_casts.append(
                {
                    "cast_number": cast_index + 1,
                    "time": float(median(timings)),
                    "logs_included": len(timings),
                }
            )

    return {
        "logs_included": len(profiles),
        "seconds": seconds,
        "average_allied_dps": average_allied_dps,
        "average_corrected_solo_dps": (
            average_corrected_solo_dps
        ),
        "median_venom_casts": median_venom_casts,
        "profiles": profiles,
        "errors": errors,
    }
