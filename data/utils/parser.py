from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import requests


SPIDER_VENOM_ID = 13037
SPIDER_VENOM_DURATION = 6.0

DAMAGE_MULTIPLIER = 0.8
DAMAGE_VALUE_THOUSANDS = 72.609


def normalize_dps_report_url(report_url: str) -> str:
    """Extract and normalize a dps.report permalink."""

    cleaned_url = report_url.strip()

    match = re.search(
        r"https?://(?:www\.)?dps\.report/[A-Za-z0-9_-]+",
        cleaned_url,
        flags=re.IGNORECASE,
    )

    if not match:
        raise ValueError("This does not appear to be a valid dps.report link.")

    return match.group(0)


def fetch_report_json(report_url: str) -> dict[str, Any]:
    """Download the Elite Insights JSON belonging to a dps.report link."""

    clean_url = normalize_dps_report_url(report_url)

    endpoint = (
        "https://dps.report/getJson?permalink="
        + quote(clean_url, safe="")
    )

    try:
        response = requests.get(
            endpoint,
            headers={"Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(
            f"Could not download the dps.report JSON: {error}"
        ) from error

    try:
        report = response.json()
    except requests.JSONDecodeError as error:
        raise RuntimeError(
            "dps.report did not return valid JSON."
        ) from error

    if not isinstance(report, dict):
        raise ValueError("The report JSON is not a valid object.")

    if not isinstance(report.get("players"), list):
        raise ValueError("The report does not contain valid player data.")

    return report


def parse_duration(value: Any) -> float | None:
    """Convert several Elite Insights duration formats into seconds."""

    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        numeric_value = float(value)

        if numeric_value <= 0:
            return None

        return (
            numeric_value / 1000
            if numeric_value > 1000
            else numeric_value
        )

    text = str(value).strip()

    try:
        numeric_value = float(text)

        return (
            numeric_value / 1000
            if numeric_value > 1000
            else numeric_value
        )
    except ValueError:
        pass

    minute_second_match = re.search(
        r"(\d+)m\s*(\d+(?:\.\d+)?)s(?:\s*(\d+)ms)?",
        text,
        flags=re.IGNORECASE,
    )

    if minute_second_match:
        minutes = float(minute_second_match.group(1))
        seconds = float(minute_second_match.group(2))
        milliseconds = float(minute_second_match.group(3) or 0)

        return minutes * 60 + seconds + milliseconds / 1000

    clock_match = re.match(
        r"^(\d+):(\d+(?:\.\d+)?)$",
        text,
    )

    if clock_match:
        minutes = float(clock_match.group(1))
        seconds = float(clock_match.group(2))

        return minutes * 60 + seconds

    return None


def get_killtime(report: dict[str, Any]) -> float:
    """Find the fight duration in seconds."""

    possible_durations = [
        report.get("duration"),
        report.get("durationMS"),
        report.get("fightDuration"),
        report.get("encounterDuration"),
    ]

    encounter = report.get("encounter")

    if isinstance(encounter, dict):
        possible_durations.append(encounter.get("duration"))

    for possible_duration in possible_durations:
        duration = parse_duration(possible_duration)

        if duration is not None and duration > 0:
            return duration

    raise ValueError("No valid killtime was found in the report.")


def is_spider_venom_rotation(rotation_entry: dict[str, Any]) -> bool:
    """Check whether a rotation entry represents Spider Venom."""

    skill_id = rotation_entry.get(
        "id",
        rotation_entry.get(
            "skillId",
            rotation_entry.get("skillID"),
        ),
    )

    skill_name = str(
        rotation_entry.get(
            "name",
            rotation_entry.get("skillName", ""),
        )
    ).strip().lower()

    try:
        numeric_skill_id = int(skill_id)
    except (TypeError, ValueError):
        numeric_skill_id = None

    return (
        numeric_skill_id == SPIDER_VENOM_ID
        or skill_name == "spider venom"
    )


def get_rotation_casts(
    rotation_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return casts from the different JSON structures EI may use."""

    for field_name in ("skills", "casts", "rotation"):
        casts = rotation_entry.get(field_name)

        if isinstance(casts, list):
            return [
                cast
                for cast in casts
                if isinstance(cast, dict)
            ]

    return []


def get_cast_start_seconds(cast: dict[str, Any]) -> float | None:
    """Read a cast timestamp and convert milliseconds to seconds."""

    possible_fields = (
        "castTime",
        "time",
        "start",
        "startTime",
        "timestamp",
        "activationTime",
        "t",
    )

    for field_name in possible_fields:
        value = cast.get(field_name)

        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue

        return (
            numeric_value / 1000
            if numeric_value > 1000
            else numeric_value
        )

    return None


def calculate_effective_casts(
    raw_casts: int,
    last_cast_start: float | None,
    killtime: float,
) -> float:
    """Count a final cast proportionally when the fight ends early."""

    if raw_casts <= 0 or last_cast_start is None:
        return float(raw_casts)

    active_time = killtime - last_cast_start

    if active_time >= SPIDER_VENOM_DURATION:
        return float(raw_casts)

    if active_time <= 0:
        return float(raw_casts - 1)

    partial_cast = active_time / SPIDER_VENOM_DURATION

    return raw_casts - 1 + partial_cast


def get_spider_venom_data(
    report: dict[str, Any],
    killtime: float,
) -> dict[str, float | int | None]:
    """Find all Spider Venom casts across the report."""

    players = report.get("players", [])

    raw_casts = 0
    last_cast_start: float | None = None

    for player in players:
        if not isinstance(player, dict):
            continue

        rotation = player.get("rotation")

        if not isinstance(rotation, list):
            continue

        for rotation_entry in rotation:
            if not isinstance(rotation_entry, dict):
                continue

            if not is_spider_venom_rotation(rotation_entry):
                continue

            casts = get_rotation_casts(rotation_entry)

            for cast in casts:
                raw_casts += 1

                cast_start = get_cast_start_seconds(cast)

                if cast_start is not None:
                    if (
                        last_cast_start is None
                        or cast_start > last_cast_start
                    ):
                        last_cast_start = cast_start

    if raw_casts == 0:
        raise ValueError(
            "No Spider Venom casts were found in this report."
        )

    effective_casts = calculate_effective_casts(
        raw_casts,
        last_cast_start,
        killtime,
    )

    if last_cast_start is None:
        active_time_last_cast = None
    else:
        active_time_last_cast = max(
            0.0,
            min(
                SPIDER_VENOM_DURATION,
                killtime - last_cast_start,
            ),
        )

    return {
        "raw_casts": raw_casts,
        "effective_casts": effective_casts,
        "last_cast_start": last_cast_start,
        "active_time_last_cast": active_time_last_cast,
    }


def calculate_venom_dps_thousands(
    effective_casts: float,
    killtime: float,
) -> float:
    """
    Calculate Spider Venom DPS in thousands.

    Example: 5.336 represents 5,336 DPS.
    """

    if killtime <= 0:
        raise ValueError("Killtime must be greater than zero.")

    damage_per_cast_thousands = (
        DAMAGE_MULTIPLIER * DAMAGE_VALUE_THOUSANDS
    )

    return (
        effective_casts
        * damage_per_cast_thousands
        / killtime
    )


def analyse_basic_report(report_url: str) -> dict[str, Any]:
    """Run the first benchmark calculations for one report."""

    report = fetch_report_json(report_url)
    killtime = get_killtime(report)

    venom = get_spider_venom_data(
        report,
        killtime,
    )

    venom_dps_thousands = calculate_venom_dps_thousands(
        effective_casts=float(venom["effective_casts"]),
        killtime=killtime,
    )

    return {
        "report_url": normalize_dps_report_url(report_url),
        "fight_name": report.get("fightName", "Unknown fight"),
        "success": report.get("success"),
        "killtime": killtime,
        "raw_venom_casts": venom["raw_casts"],
        "effective_venom_casts": venom["effective_casts"],
        "last_venom_cast_start": venom["last_cast_start"],
        "last_venom_active_time": venom["active_time_last_cast"],
        "venom_dps_thousands": venom_dps_thousands,
        "venom_dps": venom_dps_thousands * 1000,
    }
def parse_guild_wars_integer(value: str | int | float) -> int:
    """
    Convert Guild Wars 2-style numbers into whole integers.

    Accepted examples:
    40403
    40.403
    40,403
    """

    if isinstance(value, (int, float)):
        return round(value)

    text = str(value).strip().replace(" ", "")

    if not text:
        raise ValueError("The End Number is empty.")

    digits_only = text.replace(".", "").replace(",", "")

    if not re.fullmatch(r"-?\d+", digits_only):
        raise ValueError(
            "The End Number must look like 40403, 40.403 or 40,403."
        )

    return int(digits_only)


def format_guild_wars_integer(value: int | float) -> str:
    """
    Format a whole number using Guild Wars 2-style separators.

    Example:
    44435 -> 44.435
    """

    rounded_value = round(float(value))

    return f"{rounded_value:,}".replace(",", ".")


def calculate_allies_damage(
    end_number: str | int | float,
    venom_dps_thousands: float,
) -> dict[str, int | float | str]:
    """
    Calculate the spreadsheet-compatible Allies Damage value.

    Venom DPS is supplied in thousands:
    4.032 means 4,032 DPS.
    """

    personal_end_number = parse_guild_wars_integer(end_number)

    venom_dps = round(float(venom_dps_thousands) * 1000)

    allies_damage = personal_end_number + venom_dps

    return {
        "end_number": personal_end_number,
        "venom_dps": venom_dps,
        "allies_damage": allies_damage,
        "formatted_end_number": format_guild_wars_integer(
            personal_end_number
        ),
        "formatted_venom_dps": format_guild_wars_integer(
            venom_dps
        ),
        "formatted_allies_damage": format_guild_wars_integer(
            allies_damage
        ),
    }